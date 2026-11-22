"""LinkedIn ağ botu (scripts/ag_buyut.py) yönetimi: durum, başlat / durdur, son davetler ve kayıtlar.

Bot panelden bağımsız bir süreçtir (panel kapansa da çalışır). Kendi durumunu logs/ag_botu_<kullanıcı>.json
dosyasına yazar; panel bu dosyayı ve süreç numarasını (PID) okur.
"""
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timedelta

from app import context, dbconn, guard
from app.settings import AUTO_APPLY_MIN_SCORE, BASE_DIR, LOGS_DIR, STATUS_APPLIED_VERIFIED

SCRIPT = os.path.join(BASE_DIR, "scripts", "ag_buyut.py")
from app.netbot_limits import LIMITS, WORK_HOURS  # noqa: E402

DAILY, WEEKLY = int(LIMITS["MAX_DAILY_INVITES"]), int(LIMITS["MAX_WEEKLY_INVITES"])
_HIDDEN_COMPANIES = {"", "-", "gizli", "gizli şirket", "gizli firma", "confidential", "anonymous", "belirtilmemiş"}

_SEARCHES = {
    "it": [
        ("İnsan Kaynakları Müdürü", "hr"), ("İşe Alım Yöneticisi", "hr"), ("IT Recruiter", "hr"),
        ("Sistem Yöneticisi", "it"), ("İşe Alım Uzmanı", "hr"), ("Network Engineer", "it"),
        ("Siber Güvenlik", "it"), ("Bilgi İşlem", "it"), ("Talent Acquisition", "hr"),
        ("Sistem Uzmanı", "it"), ("Bilgi Güvenliği", "it"), ("DevOps", "it"),
        ("İnsan Kaynakları Yöneticisi", "hr"), ("Ağ Yöneticisi", "it"),
    ],
    "ik": [
        ("İnsan Kaynakları Müdürü", "hr"), ("İşe Alım Yöneticisi", "hr"), ("İnsan Kaynakları Direktörü", "hr"),
        ("HR Business Partner", "hr"), ("Talent Acquisition", "hr"), ("İşe Alım Uzmanı", "hr"),
        ("İnsan Kaynakları Yöneticisi", "hr"),
    ],
    "genel": [
        ("İnsan Kaynakları Müdürü", "hr"), ("İşe Alım Yöneticisi", "hr"), ("İşe Alım Uzmanı", "hr"),
        ("Talent Acquisition", "hr"), ("İnsan Kaynakları Yöneticisi", "hr"),
    ],
}


def search_plan(field="it"):
    """Kullanıcı alanına göre (şirket içi roller, şirketten bağımsız aramalar) döner."""
    f = field if field in _SEARCHES else "genel"
    roles = ["hr", "it"] if f == "it" else ["hr"]
    return roles, list(_SEARCHES[f])


def _tr_norm(name):
    return (name or "").strip().replace("I", "ı").replace("İ", "i").lower()


def priority_companies(jobs_df=None, min_score=AUTO_APPLY_MIN_SCORE):
    """Başvurulan ve yüksek uyumlu ilanların şirketleri (önce başvurulanlar, sonra en yüksek puanlılar)."""
    if jobs_df is None:
        from database.db_manager import get_all_jobs
        jobs_df = get_all_jobs()
    if jobs_df is None or jobs_df.empty:
        return []
    from database.stats import parse_score
    seen, out = set(), []

    def add(name):
        clean = (name or "").strip()
        key = _tr_norm(clean)
        if not key or key in _HIDDEN_COMPANIES or key in seen or "gizli" in key:
            return
        seen.add(key)
        out.append(clean)

    applied = jobs_df[jobs_df["Durum"] == STATUS_APPLIED_VERIFIED]
    for c in applied["Şirket"].dropna().tolist():
        add(c)
    scored = jobs_df.copy()
    scored["_p"] = scored["ATS Uyum"].map(parse_score)
    high = scored[scored["_p"].notna() & (scored["_p"] >= min_score)].sort_values("_p", ascending=False)
    for c in high["Şirket"].dropna().tolist():
        add(c)
    return out


def merge_companies(priority, base):
    """Öncelikli şirketleri başa alır, sabit listeyle tekrarsız birleştirir."""
    seen, out = set(), []
    for name in list(priority) + list(base):
        key = _tr_norm(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out


def state_path(slug):
    return os.path.join(LOGS_DIR, f"ag_botu_{slug}.json")


def log_path(slug):
    return os.path.join(LOGS_DIR, f"ag_botu_{slug}.log")


def write_state(slug, **fields):
    """Bot tarafından çağrılır: durum dosyasını günceller (atomik yazma)."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    data = read_state(slug)
    data.update(fields, updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    tmp = state_path(slug) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, state_path(slug))


def read_state(slug):
    try:
        with open(state_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # süreç var, başka kullanıcıya ait


def running_pid(slug):
    """Çalışan botun PID'i; yoksa None. Durum dosyası yoksa (eski sürümle başlatılmış bot) süreç listesine bakar."""
    pid = read_state(slug).get("pid")
    if pid_alive(pid):
        return int(pid)
    try:
        out = subprocess.run(["pgrep", "-f", "scripts/ag_buyut.py"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.split():
        if line.isdigit() and _process_user(int(line)) in (slug, None):
            return int(line)
    return None


def _process_user(pid):
    """Sürecin hangi kullanıcı için çalıştığı (KO_USER ortam değişkeni); bilinmiyorsa None."""
    try:
        env = subprocess.run(["ps", "eww", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"\bKO_USER=(\S+)", env)
    return m.group(1) if m else None


def start(slug):
    """Botu panelden bağımsız başlatır (panel kapansa da çalışır; Mac uyumasın diye caffeinate ile)."""
    if running_pid(slug):
        return False, "Bot zaten çalışıyor."
    os.makedirs(LOGS_DIR, exist_ok=True)
    env = {**os.environ, "KO_USER": slug, "PYTHONUNBUFFERED": "1", **LIMITS}
    cmd = ["caffeinate", "-ims", sys.executable, "-u", SCRIPT]
    with open(log_path(slug), "a", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    write_state(slug, state="başlatılıyor", launcher_pid=proc.pid, started=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return True, "Bot başlatıldı."


def stop(slug):
    pid = running_pid(slug)
    if not pid:
        write_state(slug, state="durduruldu")
        return False, "Bot zaten çalışmıyor."
    try:
        os.kill(pid, signal.SIGTERM)  # bot SIGTERM'de durumunu 'durduruldu' yazıp çıkar; caffeinate de kapanır
    except ProcessLookupError:
        pass
    write_state(slug, state="durduruldu", pid=None)
    return True, "Bot durduruldu."


def invite_counts(now=None):
    """(son 24 saat, son 7 gün, toplam) LinkedIn davet sayısı — hesap koruması da sınırı bu pencerelerle uygular."""
    now = now or datetime.now()
    return (guard.count("LinkedIn", guard.INVITE, now - timedelta(days=1)), guard.count("LinkedIn", guard.INVITE, now - timedelta(days=7)),
            guard.count("LinkedIn", guard.INVITE, datetime(2000, 1, 1)))


_NAME = re.compile(r"kişi=([^;]+)")
_COMPANY = re.compile(r"şirket=([^;|]+)(\|bt)?")
_URL = re.compile(r"url=(\S+)")


def parse_invite(detail):
    """'şirket=aselsan|bt; kişi=Ali Veli; url=https://...' → {"Kişi", "Kaynak", "Profil"}."""
    name = (_NAME.search(detail or "") or [None, ""])[1].strip()
    url = (_URL.search(detail or "") or [None, ""])[1].strip()
    m = _COMPANY.search(detail or "")
    source = (f"{m.group(1).strip().title()} · {'BT' if m.group(2) else 'İK'}") if m else "Genel arama"
    if name.startswith("http"):
        name = ""
    return {"Kişi": name or "(adsız)", "Kaynak": source, "Profil": url}


def recent_invites(limit=15):
    conn = dbconn.connect(guard.db_file())
    try:
        rows = conn.execute("SELECT created_at, detail FROM activity_log WHERE platform='linkedin' AND action='invite' "
                            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [{"Zaman": f"{t[8:10]}.{t[5:7]} {t[11:16]}", **parse_invite(d)} for t, d in rows]  # 19.11 22:59


def recent_log(slug, lines=12):
    """Botun son anlamlı kayıt satırları (tarayıcı/kazıma ayrıntıları hariç)."""
    path = log_path(slug)
    if not os.path.exists(path):
        legacy = os.path.join(LOGS_DIR, "ag_botu.log")  # ilk sürüm tek dosyaya yazıyordu
        path = legacy if os.path.exists(legacy) else path
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-400:]
    except FileNotFoundError:
        return []
    keep = [l.rstrip() for l in tail if re.match(r"^\d{2}\.\d{2} \d{2}:\d{2} ", l) and "son 30 günde" not in l]
    return keep[-lines:]


def status(slug, now=None):
    """Kartın gösterdiği özet: {"running", "state", "pid", "today", "week", "total", "updated", "next"}"""
    now = now or datetime.now()
    pid = running_pid(slug)
    st = read_state(slug)
    today, week, total = invite_counts(now)
    state = st.get("state") or ("çalışıyor" if pid else "durduruldu")
    if not pid:
        state = state if state in ("bitti", "giriş gerekli") else "durduruldu"
    elif not (WORK_HOURS[0] <= now.hour < WORK_HOURS[1]):
        state = "mesai dışı"
    elif state in ("durduruldu", "başlatılıyor"):
        state = "çalışıyor"
    return {"running": bool(pid), "state": state, "pid": pid, "today": today, "week": week, "total": total,
            "updated": st.get("updated", ""), "detail": st.get("detail", ""), "sent_session": st.get("sent", 0)}
