"""Otomatik İlan Avcısı (scripts/ilan_avcisi.py) yönetimi: durum, başlat/durdur, hazır fırsatlar ve kayıtlar.

Panelden bağımsız bir arka plan sürecidir (panel kapansa da çalışır; Mac uyumasın diye caffeinate ile).
Hedef pozisyonları periyodik tarar, yeni ilanları analiz eder, yüksek uyumlu (%75+) ilanlar için ön yazı ve
ilana özel CV'yi önceden hazırlar; başvuru göndermeyi her zaman kullanıcının onayına bırakır.
"""
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime

from app.settings import BASE_DIR, LOGS_DIR, STATUS_ANALYZED
from database.stats import parse_score

SCRIPT = os.path.join(BASE_DIR, "scripts", "ilan_avcisi.py")
WORK_HOURS = (8, 23)
INTERVAL_MIN = int(os.getenv("JOBBOT_INTERVAL_MIN", "120"))
PREP_MIN_SCORE = int(os.getenv("JOBBOT_PREP_MIN_SCORE", "75"))
MAX_ANALYZE_PER_CYCLE = int(os.getenv("JOBBOT_MAX_ANALYZE", "10"))
MAX_PREP_PER_CYCLE = int(os.getenv("JOBBOT_MAX_PREP", "3"))


def state_path(slug):
    return os.path.join(LOGS_DIR, f"ilan_avcisi_{slug}.json")


def log_path(slug):
    return os.path.join(LOGS_DIR, f"ilan_avcisi_{slug}.log")


def read_state(slug):
    try:
        with open(state_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(slug, **fields):
    """Bot tarafından çağrılır: durum dosyasını atomik günceller."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    data = read_state(slug)
    data.update(fields, updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    tmp = state_path(slug) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, state_path(slug))


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def _process_user(pid):
    try:
        env = subprocess.run(["ps", "eww", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"\bKO_USER=(\S+)", env)
    return m.group(1) if m else None


def running_pid(slug):
    pid = read_state(slug).get("pid")
    if pid_alive(pid):
        return int(pid)
    try:
        out = subprocess.run(["pgrep", "-f", "scripts/ilan_avcisi.py"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.split():
        if line.isdigit() and _process_user(int(line)) in (slug, None):
            return int(line)
    return None


def start(slug, include_kariyernet=True, auto_cv=True, auto_sync=True):
    """İlan avcısını panelden bağımsız arka planda başlatır."""
    if running_pid(slug):
        return False, "İlan avcısı zaten çalışıyor."
    os.makedirs(LOGS_DIR, exist_ok=True)
    env = {
        **os.environ,
        "KO_USER": slug,
        "PYTHONUNBUFFERED": "1",
        "JOBBOT_KARIYERNET": "1" if include_kariyernet else "0",
        "JOBBOT_AUTO_CV": "1" if auto_cv else "0",
        "JOBBOT_AUTO_SYNC": "1" if auto_sync else "0",
    }
    cmd = ["caffeinate", "-ims", sys.executable, "-u", SCRIPT]
    with open(log_path(slug), "a", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    write_state(slug, state="başlatılıyor", launcher_pid=proc.pid,
                started=datetime.now().strftime("%Y-%m-%d %H:%M"),
                options={"kariyernet": include_kariyernet, "auto_cv": auto_cv, "auto_sync": auto_sync})
    return True, "Otomatik ilan avcısı başlatıldı."


def stop(slug):
    pid = running_pid(slug)
    if not pid:
        write_state(slug, state="durduruldu", pid=None)
        return False, "İlan avcısı zaten çalışmıyor."
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    write_state(slug, state="durduruldu", pid=None)
    return True, "Otomatik ilan avcısı durduruldu."


def recent_log(slug, lines=15):
    try:
        with open(log_path(slug), encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-300:]
    except FileNotFoundError:
        return []
    keep = [l.rstrip() for l in tail if re.match(r"^\d{2}\.\d{2} \d{2}:\d{2} ", l)]
    return keep[-lines:]


def ready_opportunities(jobs_df, min_score=PREP_MIN_SCORE):
    """Başvurulmamış, puanı min_score+ olan fırsatlar (ön yazı / özel CV hazırlık bilgisiyle)."""
    if jobs_df is None or jobs_df.empty:
        return []
    d = jobs_df[jobs_df["Durum"] == STATUS_ANALYZED].copy()
    if d.empty:
        return []
    d["_puan"] = d["ATS Uyum"].map(parse_score)
    d = d[d["_puan"].notna() & (d["_puan"] >= min_score)].sort_values("_puan", ascending=False)
    out = []
    for _, r in d.iterrows():
        cv_path = r.get("tailored_cv_path")
        has_cv = isinstance(cv_path, str) and bool(cv_path.strip()) and os.path.exists(cv_path)
        has_cl = isinstance(r.get("cover_letter"), str) and len(r["cover_letter"].strip()) > 50
        out.append({
            "id": int(r["id"]),
            "Puan": int(r["_puan"]),
            "Şirket": r["Şirket"],
            "Pozisyon": r["Pozisyon"],
            "Kaynak": r["Kaynak"],
            "Ön yazı": "Hazır" if has_cl else "Bekliyor",
            "Özel CV": "Hazır" if has_cv else "Bekliyor",
            "İlan": r.get("url", ""),
        })
    return out


def notify_mac(title, message):
    """macOS bildirim merkezine sessizce bildirim gönderir (macOS dışı / hata durumunda yok sayılır)."""
    if sys.platform != "darwin":
        return False
    safe_t = (title or "").replace("\\", "").replace('"', "'")[:80]
    safe_m = (message or "").replace("\\", "").replace('"', "'")[:200]
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_m}" with title "{safe_t}"'],
            capture_output=True, timeout=5, check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def status(slug, now=None):
    now = now or datetime.now()
    pid = running_pid(slug)
    st = read_state(slug)
    state = st.get("state") or ("çalışıyor" if pid else "durduruldu")
    if not pid:
        state = state if state in ("bitti",) else "durduruldu"
    elif not (WORK_HOURS[0] <= now.hour < WORK_HOURS[1]):
        state = "mesai dışı"
    elif state in ("durduruldu", "başlatılıyor"):
        state = "çalışıyor"
    return {
        "running": bool(pid),
        "state": state,
        "pid": pid,
        "found_total": int(st.get("found_total", 0)),
        "analyzed_total": int(st.get("analyzed_total", 0)),
        "prepared_total": int(st.get("prepared_total", 0)),
        "next_run": st.get("next_run", ""),
        "updated": st.get("updated", ""),
        "detail": st.get("detail", ""),
        "options": st.get("options") or {"kariyernet": True, "auto_cv": True, "auto_sync": True},
    }
