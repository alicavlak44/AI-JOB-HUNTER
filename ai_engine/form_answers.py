"""Başvuru formlarındaki bilinen soruları CV'deki GERÇEK bilgilerle cevaplar.

GitHub'daki Easy Apply botlarındaki "sık sorulan alanları otomatik doldur" fikri, ama:
- Sadece CV'de / documents/profile.json'da olan bilgi kullanılır; bilinmeyen soru BOŞ bırakılır
  (bot durur ve kullanıcıya bırakır). Uydurma cevap yok.
- Sadece boş alanlar doldurulur; platformun önceden doldurduğu değerlere dokunulmaz.
"""
import re

from ai_engine.cv_profile import build_profile, tr_lower

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+?90[\s-]*)?\(?0?\s*\(?5\d{2}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
CITIES = ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya", "Konya", "Eskişehir", "Kocaeli"]

# (anahtar, etiket kalıpları) — etiket Türkçe küçük harfe çevrilip aranır
FIELD_PATTERNS = [
    ("years", [r"\bkaç yıl(lık)? (iş |toplam |profesyonel )?deneyim", r"\btoplam (iş )?deneyim", r"\byıl(lık)? deneyim(iniz)?\b",
               r"\byears? of (total |professional |work )?experience\b", r"\bhow many years\b"]),
    ("email", [r"\be-?posta\b", r"\bemail\b", r"\be-mail\b"]),
    ("phone", [r"\btelefon", r"\bgsm\b", r"\bcep\b", r"\bphone\b", r"\bmobile\b"]),
    ("city", [r"\bşehir", r"\bikamet", r"\bcity\b", r"\blocation\b", r"\bkonum\b", r"\byaşadığınız il\b"]),
]
# Bu ifadeler varsa soru başka bir şeyi soruyor → cevaplama (kullanıcıya kalır)
NEGATIVE_PATTERNS = [r"\bdoğum", r"\bbirth", r"\bnüfus", r"\bmaaş", r"\bsalary", r"\bnotice", r"\bacil durum",
                     r"\bemergency", r"\breferans", r"\breference", r"\bşirket(in)? (telefon|e-?posta)",
                     r"\bcompany (phone|email)"]
# "Kubernetes ile kaç yıl", "years of experience with Linux" → belirli bir beceri soruluyor; toplam yıl YAZILMAZ
SKILL_SPECIFIC = re.compile(r"\b(with|in|using|on)\b\s+\S|\S+\s+ile\b|\S+\s+(konusunda|alanında)\b", re.I)


def _digits_phone(raw):
    d = re.sub(r"\D", "", raw)
    if d.startswith("90") and len(d) == 12:
        d = "0" + d[2:]
    if len(d) == 10 and d.startswith("5"):
        d = "0" + d
    return d if len(d) == 11 and d.startswith("05") else None


def answers_from_cv(cv_text, today=None):
    """CV metninden form cevapları. Bulunamayan anahtar sözlükte yer almaz."""
    out = {}
    text = cv_text or ""
    m = EMAIL_RE.search(text)
    if m:
        out["email"] = m.group(0)
    for m in PHONE_RE.finditer(text):
        phone = _digits_phone(m.group(0))
        if phone:
            out["phone"] = phone
            break
    head = text[:1500]
    # şehir: adres satırı ("Ankara, Keçiören") → yoksa tek bir şehir geçiyorsa o; birden fazla ve adres yoksa BOŞ
    addr = [c for line in head.split("\n") for c in CITIES
            if re.match(rf"\s*{c}\s*[,/-]", line) and "doğum" not in tr_lower(line)]
    found = sorted({c for c in CITIES if c in head})
    if addr:
        out["city"] = addr[0]
    elif len(found) == 1:
        out["city"] = found[0]
    try:
        months = build_profile(text, today).professional_months
    except Exception:
        months = 0
    if months:
        out["years"] = str(months // 12)
    return out


def field_key(label):
    low = tr_lower(label or "")
    if any(re.search(p, low) for p in NEGATIVE_PATTERNS):
        return None
    for key, patterns in FIELD_PATTERNS:
        if any(re.search(p, low) for p in patterns):
            return key
    return None


def answer_for(label, input_type, answers):
    """Etiketi bilinen bir soruysa cevabı, değilse None döner (alan kullanıcıya kalır)."""
    key = field_key(label)
    if key is None or key not in answers:
        return None
    if input_type == "email" and key != "email":
        return None
    if input_type == "number" and key != "years":
        return None
    if key == "years" and (input_type not in ("number", "text", "") or SKILL_SPECIFIC.search(tr_lower(label))):
        return None
    return answers[key]
