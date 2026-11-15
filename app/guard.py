"""Hesap koruması (anti-ban).

Her bot işlemi (tarama, başvuru, bağlantı daveti) activity_log tablosuna yazılır.
Yeni bir işlemden ÖNCE check() geçmişe bakar:
  1. Platform yakın zamanda engel / doğrulama / 429 gösterdiyse → bekleme süresi bitene kadar DUR.
  2. Son işlemden bu yana en az bekleme süresi geçmediyse → bekle.
  3. Saatlik / günlük / haftalık limit dolduysa → DUR.
Platform engel belirtisi gösterirse report_block() çağrılır; o platformda tüm işler durur.

Bu modül platform korumalarını aşmaz (CAPTCHA çözmez, gizlenmez); sadece hesabı
insan hızının altında tutar ve uyarı görünce durur.
"""
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import settings
from app.logger import get_logger

log = get_logger("guard")

DB_PATH = settings.DB_PATH  # testler bunu geçici dosyayla değiştirir

APPLY, SCRAPE, INVITE, SYNC, FETCH, BLOCKED = "apply", "scrape", "invite", "sync", "fetch", "blocked"

# (saatlik, günlük, haftalık, iki işlem arası en az saniye); None = sınır yok
LIMITS = {
    APPLY: (settings.MAX_HOURLY_APPLICATIONS, settings.MAX_DAILY_APPLICATIONS,
            settings.MAX_WEEKLY_APPLICATIONS, settings.MIN_APPLY_INTERVAL_SEC),
    SCRAPE: (settings.MAX_HOURLY_SCRAPES, settings.MAX_DAILY_SCRAPES, None, settings.MIN_SCRAPE_INTERVAL_SEC),
    INVITE: (None, settings.MAX_DAILY_INVITES, settings.MAX_WEEKLY_INVITES, settings.MIN_INVITE_INTERVAL_SEC),
    SYNC: (2, 6, None, 600),
    FETCH: (20, 150, None, 5),  # tek ilan metni okuma (toplu analizde)  # hesap senkronu: sadece okuma, ama sık sayfa gezmek de dikkat çeker
}
ACTION_NAMES = {APPLY: "başvuru", SCRAPE: "tarama", INVITE: "bağlantı daveti", SYNC: "hesap senkronu", FETCH: "ilan okuma"}

# Sayfada görülürse platform bizi fark etmiş demektir → dur (küçük harfle aranır).
# Sadece platformların UYARI CÜMLELERİ: "captcha", "security check" gibi genel kelimeler ilan metinlerinde
# de geçtiği için (ör. güvenlik ilanları) yanlış alarm verir, kullanılmaz.
BLOCK_SIGNS = [
    "let's do a quick security check", "hızlı bir güvenlik kontrolü yapalım",
    "unusual activity from your account", "hesabınızda olağan dışı etkinlik", "hesabınızda olağandışı etkinlik",
    "your account has been restricted", "hesabınız kısıtlandı", "hesabınız geçici olarak kısıtlandı",
    "i'm not a robot", "robot olmadığınızı doğrulayın",
    "you've reached the weekly invitation limit", "haftalık davet sınırına ulaştınız",
]  # "too many requests" yok: HTTP 429 zaten yakalanıyor, ilan metinlerinde (ör. "429 Too Many Requests") geçebiliyor
BLOCK_URL_HINTS = ["/checkpoint/challenge"]  # /authwall = sadece oturum kapalı, engel DEĞİL
BLOCK_HTTP_CODES = {429, 999}  # 999 = LinkedIn'in bot cevabı


@dataclass
class Decision:
    ok: bool
    reason: str = ""
    wait_seconds: float = 0.0


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL, action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_activity ON activity_log(platform, action, created_at)")
    return conn


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def record(platform, action, detail="", now=None):
    now = now or datetime.now()
    conn = _connect()
    try:
        conn.execute("INSERT INTO activity_log(platform, action, detail, created_at) VALUES (?,?,?,?)",
                     (platform.lower(), action, (detail or "")[:300], _fmt(now)))
        conn.commit()
    finally:
        conn.close()


def count(platform, action, since):
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM activity_log WHERE platform=? AND action=? AND created_at>=?",
                            (platform.lower(), action, _fmt(since))).fetchone()[0]
    finally:
        conn.close()


def _last(platform, action):
    conn = _connect()
    try:
        row = conn.execute("SELECT created_at, detail FROM activity_log WHERE platform=? AND action=? "
                           "ORDER BY created_at DESC LIMIT 1", (platform.lower(), action)).fetchone()
    finally:
        conn.close()
    return (datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"), row[1]) if row else (None, None)


def check(platform, action, now=None):
    """İşlem şimdi yapılabilir mi? Geçmiş aktiviteye bakar."""
    now = now or datetime.now()
    name = ACTION_NAMES.get(action, action)

    blocked_at, why = _last(platform, BLOCKED)
    if blocked_at:
        until = blocked_at + timedelta(hours=settings.BLOCK_COOLDOWN_HOURS)
        if now < until:
            return Decision(False, f"{platform} {_fmt(blocked_at)} tarihinde uyarı verdi ({why}). Hesabı korumak için "
                                   f"{_fmt(until)} saatine kadar bot işlemleri durduruldu.",
                            (until - now).total_seconds())

    hourly, daily, weekly, min_gap = LIMITS.get(action, (None, None, None, 0))

    last_at, _ = _last(platform, action)
    if last_at and min_gap:
        gap = (now - last_at).total_seconds()
        if gap < min_gap:
            return Decision(False, f"Son {name} işleminden bu yana {gap:.0f} sn geçti; en az {min_gap:.0f} sn beklenmeli.",
                            min_gap - gap)

    for limit, window, label in ((hourly, timedelta(hours=1), "saatlik"),
                                 (daily, timedelta(days=1), "günlük"),
                                 (weekly, timedelta(days=7), "haftalık")):
        if limit is not None and count(platform, action, now - window) >= limit:
            reset = _reset_time(platform, action, now - window, limit, window) or now + window
            mins = max(1, round((reset - now).total_seconds() / 60))
            when = f"{mins} dk sonra ({reset:%H:%M})" if mins < 120 else f"{reset:%d.%m %H:%M}"
            return Decision(False, f"{platform} {label} {name} sınırı doldu ({limit}). Hesap güvenliği için "
                                   f"{when} tekrar deneyin.", (reset - now).total_seconds())
    return Decision(True)


def _reset_time(platform, action, since, limit, window):
    """Pencere içindeki kayıtlardan biri düşüp sınırın altına inilen an: (sondan limit'inci kaydın zamanı) + pencere."""
    conn = _connect()
    try:
        row = conn.execute("SELECT created_at FROM activity_log WHERE platform=? AND action=? AND created_at>=? "
                           "ORDER BY created_at DESC LIMIT 1 OFFSET ?",
                           (platform.lower(), action, _fmt(since), limit - 1)).fetchone()
    finally:
        conn.close()
    return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") + window if row else None


def wait_turn(platform, action, max_wait=30, sleep=time.sleep):
    """Kısa bekleme gerekiyorsa (≤ max_wait sn) bekleyip tekrar kontrol eder. Sayfalı işlemlerde HER sayfadan önce."""
    decision = check(platform, action)
    if not decision.ok and decision.wait_seconds <= max_wait:
        sleep(decision.wait_seconds + random.uniform(1, 4))
        decision = check(platform, action)
    return decision


def is_blocked(platform, now=None):
    """Platform şu an engel bekleme süresinde mi?"""
    blocked_at, _ = _last(platform, BLOCKED)
    now = now or datetime.now()
    return bool(blocked_at and now < blocked_at + timedelta(hours=settings.BLOCK_COOLDOWN_HOURS))


def detect_block(text=None, http_status=None, url=None):
    """Sayfa metninde / HTTP kodunda / adreste engel belirtisi varsa nedenini döndürür, yoksa None."""
    if http_status in BLOCK_HTTP_CODES:
        return f"HTTP {http_status}"
    for hint in BLOCK_URL_HINTS:
        if url and hint in url:
            return f"doğrulama sayfası ({hint})"
    # Türkçe küçük harf: 'İ'.lower() Python'da 'i̇' verir, 'I' → 'ı' olmalı
    # Önceden .lower() ile küçültülmüş metinde 'İ' → 'i' + birleşik nokta (U+0307) olur; onu da temizle
    low = (text or "").replace("I", "ı").replace("İ", "i").lower().replace("̇", "")
    low_ascii_i = (text or "").lower().replace("̇", "")  # İngilizce metinler ('I'm not a robot') için
    fold = lambda t: t.replace("ı", "i")  # Python 'DIŞI'.lower() → 'dişi'; ı/i farkını yok say
    folded = fold(low) + "\n" + fold(low_ascii_i)
    for sign in BLOCK_SIGNS:
        if fold(sign) in folded:
            return f"'{sign}' uyarısı"
    return None


def done_recently(platform, action, detail_contains, days=30, now=None):
    """Aynı hedefe (ör. aynı şirket) son `days` günde bu işlem yapıldı mı? Tekrar/spam önler."""
    now = now or datetime.now()
    conn = _connect()
    try:
        return conn.execute("SELECT 1 FROM activity_log WHERE platform=? AND action=? AND created_at>=? "
                            "AND detail LIKE ? LIMIT 1",  # çağıran normalize anahtar verir (ör. company_key)
                            (platform.lower(), action, _fmt(now - timedelta(days=days)),
                             f"%{detail_contains or ''}%")).fetchone() is not None
    finally:
        conn.close()


def report_block(platform, reason, now=None):
    log.warning("%s engel belirtisi: %s → %s saat bekleme", platform, reason, settings.BLOCK_COOLDOWN_HOURS)
    record(platform, BLOCKED, reason, now)


def human_pause(min_sec=2.0, max_sec=5.0, sleep=time.sleep):
    """İnsan hızında rastgele bekleme (sabit aralıklı istekler bot gibi görünür)."""
    sleep(random.uniform(min_sec, max_sec))


def status(platform, now=None):
    """Panel için özet: her işlemde kullanılan / sınır."""
    now = now or datetime.now()
    out = {}
    for action, (hourly, daily, weekly, _) in LIMITS.items():
        if action in (SYNC, FETCH):
            continue
        out[ACTION_NAMES[action]] = {
            "bugün": f"{count(platform, action, now - timedelta(days=1))}/{daily if daily is not None else '∞'}",
            "hafta": f"{count(platform, action, now - timedelta(days=7))}/{weekly if weekly is not None else '∞'}",
        }
    d = check(platform, BLOCKED, now)  # BLOCKED'in limiti yok → sadece bekleme süresini kontrol eder
    out["engel"] = None if d.ok else d.reason
    return out
