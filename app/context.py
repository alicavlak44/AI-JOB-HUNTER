"""Kullanıcı bağlamı: çok kullanıcılı yapı.

Her kullanıcının AYRI: veritabanı (ilanlar, koruma kayıtları, ağ), bot tarayıcı profili (kendi LinkedIn /
Kariyer.net oturumu), CV'si, hedef alanı ve pozisyonları. Böylece biri "Bilgi İşlem", diğeri
"İnsan Kaynakları" ararken veriler, limitler ve hesaplar karışmaz.

İlk kullanıcı (DEFAULT_USER) eski konumları kullanır: database/kariyer_otonomu_v5.db, database/bot_profile,
documents/Cv.pdf — mevcut veriler ve oturumlar korunur. Diğerleri profiles/<kullanıcı>/ altında.

Etkin kullanıcı iş parçacığına özeldir (Streamlit her oturumu ayrı iş parçacığında çalıştırır).
"""
import hashlib
import unicodedata
import json
import os
import re
import secrets
import threading
from datetime import datetime

from app import settings

DEFAULT_USER = "ali-cavlak"
PROFILES_DIR = os.path.join(settings.BASE_DIR, "profiles")
USERS_FILE = os.path.join(PROFILES_DIR, "users.json")

FIELDS = {
    "it": "Bilgi Teknolojileri / Bilgi İşlem",
    "ik": "İnsan Kaynakları",
    "genel": "Diğer alanlar",
}
FIELD_POSITIONS = {
    "it": settings.DEFAULT_POSITIONS,
    "ik": ["İnsan Kaynakları Uzmanı", "İnsan Kaynakları Müdürü", "İşe Alım Uzmanı", "HR Business Partner",
           "Bordro ve Özlük İşleri Uzmanı", "Talent Acquisition Specialist"],
    "genel": [],
}

_local = threading.local()


def slugify(name):
    # 'İ'.lower() Python'da 'i' + birleşik nokta verir → önce Türkçe büyük harfleri elle çevir;
    # sonra NFKD ile aksanları ayırıp at (José → jose, ayrışık yazılmış 'İlker' → ilker)
    s = (name or "").strip().replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "kullanici"


# ---------------------------------------------------------------- kullanıcı kayıtları
def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()


def load_users():
    if not os.path.exists(USERS_FILE):
        users = {DEFAULT_USER: {"name": settings.CANDIDATE_NAME if settings.CANDIDATE_NAME != "Aday" else "Ali Cavlak",
                                "field": "it", "targets": list(settings.DEFAULT_POSITIONS), "city": "Ankara",
                                "pin": None, "salt": None, "created": datetime.now().isoformat(timespec="seconds")}}
        save_users(users)
        return users
    with open(USERS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_FILE)


def create_user(name, field="genel", targets=None, city="Ankara", pin=None):
    users = load_users()
    slug = base = slugify(name)
    n = 2
    while slug in users or os.path.exists(os.path.join(PROFILES_DIR, slug)):  # eski klasörü devralmasın
        slug, n = f"{base}-{n}", n + 1
    salt = secrets.token_hex(8) if pin else None
    users[slug] = {"name": name.strip(), "field": field if field in FIELDS else "genel",
                   "targets": [t for t in (targets or FIELD_POSITIONS.get(field, [])) if t.strip()],
                   "city": city or "Ankara", "pin": _hash_pin(pin, salt) if pin else None, "salt": salt,
                   "created": datetime.now().isoformat(timespec="seconds")}
    save_users(users)
    return slug


def update_user(slug, **fields):
    users = load_users()
    if "pin" in fields:
        pin = fields.pop("pin")
        users[slug]["salt"] = secrets.token_hex(8) if pin else None
        users[slug]["pin"] = _hash_pin(pin, users[slug]["salt"]) if pin else None
    users[slug].update(fields)
    save_users(users)


def has_pin(slug):
    return bool(load_users().get(slug, {}).get("pin"))


def verify_pin(slug, pin):
    u = load_users().get(slug)
    if not u:
        return False
    if not u.get("pin"):
        return True
    return secrets.compare_digest(u["pin"], _hash_pin(pin or "", u["salt"]))


# ---------------------------------------------------------------- etkin kullanıcı
def set_user(slug):
    _local.user = slug


def current():
    return getattr(_local, "user", None) or DEFAULT_USER


def user(slug=None):
    users = load_users()
    return users.get(slug or current()) or users.get(DEFAULT_USER) or next(iter(users.values()))


def is_default(slug=None):
    return (slug or current()) == DEFAULT_USER


def user_dir(slug=None):
    d = os.path.join(PROFILES_DIR, slug or current())
    os.makedirs(d, exist_ok=True)
    return d


def db_path(slug=None):
    return settings.DB_PATH if is_default(slug) else os.path.join(user_dir(slug), "data.db")


def chrome_profile(slug=None):
    return settings.CHROME_PROFILE if is_default(slug) else os.path.join(user_dir(slug), "chrome")


def cv_path(slug=None):
    """Arama/analizde kullanılan ana CV (PDF)."""
    own = os.path.join(user_dir(slug), "cv.pdf")
    if os.path.exists(own):
        return own
    return settings.CV_PATH if is_default(slug) else own


def extra_profile_path(slug=None):
    return (os.path.join(settings.DOCS_DIR, "profile.json") if is_default(slug)
            else os.path.join(user_dir(slug), "ek_bilgiler.json"))


def out_dir(kind, slug=None):
    """Kullanıcıya özel çıktı klasörü: 'generated_cv' | 'cover_letters' | 'reports'.
    Varsayılan kullanıcı eski konumları kullanır; diğerleri profiles/<kullanıcı>/<kind>/ — dosya adları ilan
    numarasına göre olduğundan (her kullanıcıda 1'den başlar) ortak klasör başka kişinin CV'sini ezerdi."""
    legacy = {"generated_cv": os.path.join(settings.DOCS_DIR, "generated_cv"),
              "cover_letters": settings.COVER_LETTERS_DIR, "reports": settings.REPORTS_DIR}
    d = legacy[kind] if is_default(slug) else os.path.join(user_dir(slug), kind)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- soru hafızası (kullanıcının KENDİ cevapları)
def norm_q(q):
    """Soru metnini karşılaştırılabilir hale getirir (büyük/küçük harf, yıldız, boşluk, noktalama)."""
    q = (q or "").replace("İ", "i").replace("I", "ı").lower()
    q = re.sub(r"[*?:.!()\[\]\"'’]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def qa(slug=None):
    """{normalize soru: cevap} — sadece kullanıcının verdiği cevaplar."""
    return {k: v for k, v in (user(slug).get("qa") or {}).items() if str(v).strip()}


def set_answers(answers: dict, slug=None):
    """answers: {soru metni: cevap}. Boş cevap = soruyu hafızadan sil."""
    slug = slug or current()
    users = load_users()
    q = dict(users[slug].get("qa") or {})
    for k, v in answers.items():
        k = norm_q(k)
        if str(v).strip():
            q[k] = str(v).strip()
        else:
            q.pop(k, None)
    users[slug]["qa"] = q
    pend = [p for p in users[slug].get("qa_pending", []) if norm_q(p) not in q]
    users[slug]["qa_pending"] = pend
    save_users(users)


def add_pending_questions(questions, slug=None):
    """Botun cevabını bilmediği için durduğu soruları kullanıcıya sorulmak üzere kaydeder."""
    slug = slug or current()
    users = load_users()
    known = set((users[slug].get("qa") or {}))
    pend = list(users[slug].get("qa_pending") or [])
    for q in questions:
        q = (q or "").strip().rstrip("*").strip()
        if q and norm_q(q) not in known and norm_q(q) not in {norm_q(p) for p in pend}:
            pend.append(q)
    users[slug]["qa_pending"] = pend[-100:]
    save_users(users)


def field(slug=None):
    return user(slug).get("field", "genel")


def name(slug=None):
    return user(slug).get("name") or "Aday"
