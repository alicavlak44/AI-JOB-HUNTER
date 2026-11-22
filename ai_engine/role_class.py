"""Kadro sınıfı (Tekniker / Uzman / Mühendis) ve Yeni Mezun / Junior sınıflandırıcısı.

Herkes mühendis değildir: adayın CV'sindeki eğitim ve deneyimden mühendis olup olmadığı otomatik
anlaşılır; ilanlar kadro sınıfına (🔧 Tekniker, 💼 Uzman, ⚙️ Mühendis) ve yeni mezun / junior
etiketine (🎓 Yeni Mezun) ayrılır.
"""
import re

ROLE_TECH = "Tekniker / Teknisyen"
ROLE_SPEC = "Uzman / Yönetici"
ROLE_ENG = "Mühendis"
ROLE_OTHER = "Diğer"

ALL_ROLE_CLASSES = [ROLE_TECH, ROLE_SPEC, ROLE_ENG, ROLE_OTHER]

ROLE_BADGE = {
    ROLE_TECH: "🔧 Tekniker",
    ROLE_SPEC: "💼 Uzman",
    ROLE_ENG: "⚙️ Mühendis",
    ROLE_OTHER: "📌 Diğer",
}


def _norm(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower().strip()


# Kadro sınıfı kalıpları (başlık öncelikli)
_TECH_RE = re.compile(
    r"(?<![\wçğıöşü])(?:"
    r"tekniker\w*|teknisyen\w*|technician|help\s*desk|servis\s*masası|masaüstü\s*destek|"
    r"saha\s*destek|son\s*kullanıcı\s*destek|teknik\s*destek\s*(?:eleman|personel|teknik)|"
    r"bilgi\s*işlem\s*destek|it\s*support\s*(?:technician|staff|assistant)|donanım\s*destek|"
    r"kablolama|sistem\s*operatör\w*|veri\s*merkezi\s*operatör\w*|noc\s*operatör\w*"
    r")(?![\wçğıöşü])",
    re.IGNORECASE,
)

_ENG_RE = re.compile(
    r"(?<![\wçğıöşü])(?:"
    r"mühendis\w*|müh\.|engineer\w*|architect|mimar\w*|developer|yazılım\s*geliştirici|"
    r"geliştirici|devops|sre|site\s*reliability"
    r")(?![\wçğıöşü])",
    re.IGNORECASE,
)

_SPEC_RE = re.compile(
    r"(?<![\wçğıöşü])(?:"
    r"uzman\w*|specialist|administrator|sysadmin|yönetici\w*|manager|sorumlu\w*|"
    r"analist\w*|analyst|danışman\w*|consultant|koordinatör\w*|lider\w*|lead|"
    r"direktör\w*|director|şef\w*|müdür\w*|bilgi\s*işlem|sistem\s*ve\s*ağ|ağ\s*ve\s*sistem|"
    r"it\s*support\s*specialist|sistem\s*destek"
    r")(?![\wçğıöşü])",
    re.IGNORECASE,
)

# İlan metninde açık mühendislik diploması şartı
_ENG_DEGREE_RE = re.compile(
    r"(?:mühendislik\s*fakülte|mühendisliği\s*(?:bölüm\w*\s*)?mezun|"
    r"bilgisayar[\s,/]+(?:yazılım|elektrik|elektronik|endüstri)[\s\w,/]{0,30}mühendisliği|"
    r"4\s*yıllık\s*mühendislik|b\.?sc\.?\s+in\s+[\w\s]+engineering)",
    re.IGNORECASE,
)

# Yeni mezun / Junior / Yetiştirilmek üzere kalıpları
_FRESH_GRAD_RE = re.compile(
    r"(?<![\wçğıöşü])(?:"
    r"yeni\s*mezun\w*|new\s*grad\w*|fresh\s*grad\w*|junior|jr\.?|"
    r"entry[\s-]level|yetiştirilmek\s*üzere|genç\s*yetenek|aday\s*mühendis|"
    r"management\s*trainee|early\s*career|career\s*start|başlangıç\s*seviye|"
    r"deneyimsiz|tecrübesiz|0\s*[-–—]\s*[12]\s*yıl|en\s*az\s*0\s*yıl"
    r")(?![\wçğıöşü])",
    re.IGNORECASE,
)

# CV'den mühendislik diploması / unvanı tespiti
_CV_ENG_DEGREE_RE = re.compile(
    r"(?:mühendislik\s*fakülte|[\wçğıöşü]+\s+mühendisliği|b\.?sc\.?\s+in\s+[\w\s]*engineering|"
    r"engineering\s+degree|computer\s+engineering|electrical\s+engineering|software\s+engineering)",
    re.IGNORECASE,
)
_CV_TECH_RE = re.compile(
    r"(?:ön\s*lisans|önlisans|meslek\s*yüksekokul|myo\b|tekniker\w*|teknisyen\w*|"
    r"mesleki\s*ve\s*teknik\s*anadolu\s*lisesi)",
    re.IGNORECASE,
)


def detect_candidate_role_profile(cv_text):
    """CV metninden adayın kadro profilini çıkarır (Mühendis mi, Tekniker/Uzman mı, Yeni Mezun mu?)."""
    from ai_engine.cv_profile import build_profile
    low = _norm(cv_text)
    is_engineer = bool(_CV_ENG_DEGREE_RE.search(low))
    is_technician = bool(_CV_TECH_RE.search(low))
    prof_months = 0
    if cv_text:
        try:
            prof = build_profile(cv_text)
            prof_months = prof.professional_months
            if not is_engineer and any(_ENG_RE.search(_norm(p.title)) for p in prof.periods if p.professional):
                is_engineer = True
        except Exception:
            pass
    is_fresh_grad = prof_months < 12
    if is_engineer:
        suggested = [ROLE_ENG, ROLE_SPEC]
        summary = "Mühendis & Uzman profili (CV'de mühendislik eğitimi/deneyimi var)"
    elif is_technician:
        suggested = [ROLE_TECH, ROLE_SPEC]
        summary = "Tekniker & Uzman profili (CV ön lisans / tekniker — Mühendis ilanları hariç)"
    else:
        suggested = [ROLE_SPEC, ROLE_TECH]
        summary = "Uzman & Yönetici profili (CV'de mühendislik diploması yok)"
    return {
        "is_engineer": is_engineer,
        "is_technician": is_technician,
        "is_fresh_grad": is_fresh_grad,
        "professional_months": prof_months,
        "suggested_classes": suggested,
        "summary": summary,
    }


def classify_role(title, details=""):
    """İlanı kadro sınıfına (Tekniker / Uzman / Mühendis / Diğer) ve Yeni Mezun durumuna ayırır."""
    t = _norm(title)
    d = _norm((details or "")[:2500])
    req_eng_deg = bool(_ENG_DEGREE_RE.search(d))
    is_fresh = bool(_FRESH_GRAD_RE.search(t) or _FRESH_GRAD_RE.search(d[:1200]))

    if _TECH_RE.search(t):
        rcls = ROLE_TECH
    elif _ENG_RE.search(t):
        rcls = ROLE_ENG
    elif _SPEC_RE.search(t):
        rcls = ROLE_SPEC
    elif req_eng_deg:
        rcls = ROLE_ENG
    else:
        rcls = ROLE_OTHER

    badge = ROLE_BADGE[rcls]
    display = f"{badge} · 🎓 Yeni Mezun" if is_fresh else badge
    return {
        "role_class": rcls,
        "badge": badge,
        "display": display,
        "is_fresh_grad": is_fresh,
        "requires_engineering_degree": req_eng_deg,
    }


def matches_role_prefs(title, details="", allowed_classes=None, fresh_grad_only=False):
    """İlan kullanıcının kadro sınıfı ve yeni mezun tercihine uyuyor mu?"""
    rc = classify_role(title, details)
    if fresh_grad_only and not rc["is_fresh_grad"]:
        return False
    if allowed_classes:
        allowed = set(allowed_classes)
        if rc["role_class"] not in allowed:
            return False
        # Kullanıcı Mühendis istemiyorsa, başlığı 'Uzman' olsa bile metninde açık mühendislik diploması şartı olanı ele
        if ROLE_ENG not in allowed and rc["requires_engineering_degree"]:
            return False
    return True
