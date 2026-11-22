"""Başvuru sonrası takip (CRM), yaklaşan mülakatlar, kabul edilen bağlantılar ve hazır takip mesajları.

Otomatik mesaj (DM) göndermez; kime ve ne zaman yazmanız gerektiğini çıkarır, uydurmasız hazır taslak verir.
"""
from datetime import datetime

from app import account, dbconn, guard, netbot
from app.settings import STATUS_APPLIED_VERIFIED
from database.stats import parse_score

STAGES = ["Başvuruldu", "İK Aradı", "Teknik Mülakat", "Teklif", "Olumsuz"]
INTERVIEW_STAGES = {"İK Aradı", "Teknik Mülakat"}


def _parse_dt(val):
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def due_followups(jobs_df, days=7, now=None):
    """Başvurulup `days`+ gün dönüş alınmamış (ve henüz takip edilmemiş) ilanlar — puana göre sıralı."""
    if jobs_df is None or jobs_df.empty:
        return []
    now = now or datetime.now()
    out = []
    for _, r in jobs_df.iterrows():
        if r.get("Durum") != STATUS_APPLIED_VERIFIED:
            continue
        stage = (r.get("pipeline_stage") or "").strip() if isinstance(r.get("pipeline_stage"), str) else ""
        if stage and stage != "Başvuruldu":
            continue
        applied_dt = _parse_dt(r.get("applied_at")) or _parse_dt(r.get("created_at"))
        if not applied_dt:
            continue
        age_days = (now - applied_dt).days
        if age_days < days:
            continue
        fu_dt = _parse_dt(r.get("followed_up_at"))
        if fu_dt and (now - fu_dt).days < days:
            continue
        score = parse_score(r.get("ATS Uyum")) or 0
        out.append({
            "id": int(r["id"]),
            "Şirket": r.get("Şirket") or "-",
            "Pozisyon": r.get("Pozisyon") or "-",
            "Puan": int(score),
            "Gün": age_days,
            "url": r.get("url") or "",
        })
    out.sort(key=lambda x: (-x["Puan"], -x["Gün"]))
    return out


def upcoming_interviews(jobs_df, now=None):
    """Mülakat tarihi girilmiş (bugün veya gelecek) ya da mülakat aşamasındaki ilanlar."""
    if jobs_df is None or jobs_df.empty:
        return []
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for _, r in jobs_df.iterrows():
        stage = (r.get("pipeline_stage") or "").strip() if isinstance(r.get("pipeline_stage"), str) else ""
        raw_dt = (r.get("interview_date") or "").strip() if isinstance(r.get("interview_date"), str) else ""
        dt = _parse_dt(raw_dt)
        if stage == "Olumsuz":
            continue
        if dt and dt >= today:
            out.append({
                "id": int(r["id"]),
                "Şirket": r.get("Şirket") or "-",
                "Pozisyon": r.get("Pozisyon") or "-",
                "Aşama": stage or "Mülakat",
                "Tarih": raw_dt,
                "_sort": dt,
            })
        elif stage in INTERVIEW_STAGES and not dt:
            out.append({
                "id": int(r["id"]),
                "Şirket": r.get("Şirket") or "-",
                "Pozisyon": r.get("Pozisyon") or "-",
                "Aşama": stage,
                "Tarih": "Tarih girilmedi",
                "_sort": datetime(2099, 1, 1),
            })
    out.sort(key=lambda x: x["_sort"])
    for item in out:
        item.pop("_sort", None)
    return out


def accepted_contacts(limit=20):
    """Botun davet gönderdiği kişilerden bağlantıyı kabul etmiş olanlar (en yeniden eskiye)."""
    conn = dbconn.connect(guard.db_file())
    try:
        rows = conn.execute(
            "SELECT created_at, detail FROM activity_log WHERE platform='linkedin' AND action='invite' ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    by_url = {}
    for created_at, detail in rows:
        parsed = netbot.parse_invite(detail)
        url = account.norm_url(parsed.get("Profil") or "")
        if url and url not in by_url:
            by_url[url] = {"Zaman": f"{created_at[8:10]}.{created_at[5:7]}", "Kişi": parsed["Kişi"],
                           "Kaynak": parsed["Kaynak"], "Profil": url}
    if not by_url:
        return []
    aconn = account._connect()
    try:
        q = ",".join("?" * len(by_url))
        found = aconn.execute(
            f"SELECT url, name FROM known_people WHERE kind='connection' AND url IN ({q})",
            tuple(by_url.keys()),
        ).fetchall()
    finally:
        aconn.close()
    accepted_map = {u: n for u, n in found}
    out = []
    for url, info in by_url.items():
        if url in accepted_map:
            name = accepted_map[url] or info["Kişi"]
            out.append({**info, "Kişi": name})
            if len(out) >= limit:
                break
    return out


def followup_message(job_title, company, candidate_name, days_ago=None):
    """Başvuru sonrası nazik, kısa ve uydurmasız Türkçe takip mesajı taslağı."""
    when = f"yaklaşık {days_ago} gün önce" if days_ago and days_ago >= 3 else "yakın zamanda"
    comp = (company or "şirketiniz").strip()
    pos = (job_title or "ilgili").strip()
    cand = (candidate_name or "").strip()
    sign = f"\nSaygılarımla,\n{cand}" if cand else "\nSaygılarımla."
    return (
        f"Merhaba,\n\n"
        f"{comp} bünyesindeki {pos} pozisyonuna {when} başvurumu iletmiştim. "
        f"Pozisyona ve ekibinize olan ilgim devam ediyor; sürecin güncel durumu hakkında kısaca bilgi "
        f"paylaşabilirseniz çok sevinirim. Gerekli görürseniz özgeçmişimi buradan da iletebilirim."
        f"{sign}"
    )


def welcome_connection_message(person_name, candidate_name, headline=""):
    """Daveti kabul eden İK / yönetici bağlantısına kısa, baskısız teşekkür ve tanışma mesajı."""
    first = (person_name or "").strip().split(" ")[0]
    greet = f"Merhaba {first} Hanım/Bey," if first and first != "(adsız)" else "Merhaba,"
    role = f" {headline.strip()} alanında çalışıyorum." if (headline or "").strip() else ""
    cand = (candidate_name or "").strip()
    sign = f" Teşekkürler, {cand}." if cand else " Teşekkürler."
    return (
        f"{greet} Bağlantı isteğimi kabul ettiğiniz için teşekkür ederim.{role} "
        f"Gelecekte uygun fırsatlar veya mesleki paylaşımlar için ağımızda iletişimde kalmaktan mutluluk duyarım.{sign}"
    )
