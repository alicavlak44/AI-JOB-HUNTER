"""CV'den kodla (LLM'siz) ölçülebilir bilgiler çıkarır: deneyim süresi ve eğitim alanları.

LLM tarih hesabında ve "CV'de var mı?" sorusunda hata yaptığı için bu bilgiler
deterministik olarak hesaplanır ve modele "doğrulanmış gerçek" olarak verilir.
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date

from app.settings import DOCS_DIR

PROFILE_PATH = os.path.join(DOCS_DIR, "profile.json")


def tr_lower(s: str) -> str:
    """Türkçe duyarlı küçük harfe çevirme ('İ'.lower() Python'da 'i\\u0307' ürettiği için)."""
    return (s or "").replace("I", "ı").replace("İ", "i").lower()

TR_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
PRESENT_WORDS = r"(?:günümüz|halen|devam ediyor|present|current|now)"
_MONTH_RE = "|".join(sorted(TR_MONTHS, key=len, reverse=True))
PERIOD_RE = re.compile(
    rf"(?P<m1>{_MONTH_RE})\s+(?P<y1>(?:19|20)\d{{2}})\s*[–—-]\s*"
    rf"(?:(?P<m2>{_MONTH_RE})\s+(?P<y2>(?:19|20)\d{{2}})|(?P<now>{PRESENT_WORDS}))",
    re.IGNORECASE,
)
# Bu kelimeleri içeren pozisyonlar profesyonel deneyime sayılmaz
NON_PROFESSIONAL = ("stajyer", "staj", "intern", "trainee", "gönüllü", "volunteer")

# Eğitim alanı aileleri: ilan ve CV aynı aileye düşerse "bölüm uyumlu" sayılır
FIELD_FAMILIES = {
    "bilgisayar": ["bilgisayar mühendisliği", "bilgisayar bilimleri", "computer engineering",
                   "computer science", "yazılım mühendisliği", "software engineering", "bilgisayar programcılığı"],
    "elektrik_elektronik": ["elektrik-elektronik", "elektrik ve elektronik", "elektrik mühendisliği",
                            "elektronik mühendisliği", "elektronik ve haberleşme", "elektronik-haberleşme",
                            "elektronik teknolojisi", "elektrik teknolojisi", "electrical engineering", "electronics engineering"],
    "bilisim_sistemleri": ["yönetim bilişim sistemleri", "bilişim sistemleri", "management information systems",
                           "information systems", "bilişim teknolojileri", "information technology"],
    "bilgi_guvenligi": ["bilgi güvenliği", "siber güvenlik", "information security", "cyber security"],
    "havacilik": ["havacılık ve uzay", "uçak mühendisliği", "aerospace"],
    "endustri": ["endüstri mühendisliği", "industrial engineering"],
    "makine": ["makine mühendisliği", "mechanical engineering"],
    "insan_kaynaklari": ["insan kaynakları", "human resources", "çalışma ekonomisi", "psikoloji"],
    "isletme": ["işletme", "business administration", "iktisat", "economics"],
}


@dataclass
class Period:
    title: str
    start: date
    end: date
    professional: bool

    @property
    def months(self):
        return (self.end.year - self.start.year) * 12 + (self.end.month - self.start.month) + 1


@dataclass
class CVProfile:
    periods: list = field(default_factory=list)
    professional_months: int = 0
    education_families: set = field(default_factory=set)
    extra: dict = field(default_factory=dict)  # profile.json (ehliyet, askerlik vb.)

    @property
    def professional_years(self):
        return round(self.professional_months / 12, 1)


def _merge_months(periods):
    """Çakışan dönemleri birleştirip toplam ay sayısını döner."""
    spans = sorted((p.start.year * 12 + p.start.month, p.end.year * 12 + p.end.month) for p in periods)
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e + 1:
            if cur_e is not None:
                total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s + 1
    return total


def _title_before(lines, idx):
    """Tarih satırından önceki 3 satır içindeki en üstteki metin satırı (genelde: başlık / şirket / şehir)."""
    window = [l.strip() for l in lines[max(0, idx - 3):idx]]
    window = [l for l in window if l and not l.startswith("•") and len(l) < 120]
    return window[0] if window else ""


def _experience_section(cv_text):
    """'Deneyim' başlığından bir sonraki ana başlığa (Eğitim, Sertifikalar...) kadar olan kısım."""
    lines = cv_text.splitlines()
    heads_start = ("deneyim", "iş deneyimi", "experience", "work experience", "professional experience")
    heads_end = ("eğitim", "education", "sertifikalar", "certifications", "referanslar", "references", "projeler", "projects")
    start = next((i for i, l in enumerate(lines) if tr_lower(l.strip()) in heads_start), None)
    if start is None:
        return cv_text  # başlık bulunamazsa tüm metin
    end = next((i for i in range(start + 1, len(lines)) if tr_lower(lines[i].strip()) in heads_end), len(lines))
    return "\n".join(lines[start + 1:end])


def extract_periods(cv_text, today=None):
    today = today or date.today()
    lines = _experience_section(cv_text).splitlines()
    periods = []
    for i, line in enumerate(lines):
        m = PERIOD_RE.search(tr_lower(line))
        if not m:
            continue
        start = date(int(m["y1"]), TR_MONTHS[tr_lower(m["m1"])], 1)
        end = today.replace(day=1) if m["now"] else date(int(m["y2"]), TR_MONTHS[tr_lower(m["m2"])], 1)
        if end < start:
            continue
        context = tr_lower(" ".join(lines[max(0, i - 3):i]))
        title = _title_before(lines, i)
        professional = not any(w in context for w in NON_PROFESSIONAL)
        periods.append(Period(title=title, start=start, end=end, professional=professional))
    return periods


def _education_section(cv_text):
    low = tr_lower(cv_text)
    for head in ("eğitim", "education"):
        idx = low.find("\n" + head)
        if idx != -1:
            end = len(low)
            for nxt in ("\nsertifika", "\ncertific", "\nreferans", "\nreferences", "\nprojeler", "\nprojects"):
                j = low.find(nxt, idx + 5)
                if j != -1:
                    end = min(end, j)
            return low[idx:end]
    return low


def field_families(text):
    low = tr_lower(text)
    return {fam for fam, names in FIELD_FAMILIES.items() if any(n in low for n in names)}


def _profile_path():
    from app import context
    return context.extra_profile_path()


def load_extra_profile():
    """documents/profile.json: CV'de olmayan ama formlarda sorulan bilgiler (ehliyet, askerlik...)."""
    try:
        with open(_profile_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_extra_profile(data: dict):
    """documents/profile.json dosyasını güvenli biçimde kaydeder."""
    os.makedirs(os.path.dirname(_profile_path()), exist_ok=True)
    current = load_extra_profile()
    current.update(data)
    with open(_profile_path(), "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current


def build_profile(cv_text, today=None):
    periods = extract_periods(cv_text, today)
    pro = [p for p in periods if p.professional]
    return CVProfile(
        periods=periods,
        professional_months=_merge_months(pro),
        education_families=field_families(_education_section(cv_text)),
        extra=load_extra_profile(),
    )
