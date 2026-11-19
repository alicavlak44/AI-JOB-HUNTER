"""CV Stüdyosu: CV içe aktar → düzenle → yapay zeka ile iyileştir (uydurmasız) → şablonla PDF/DOCX üret.

Çok kişili: her kişinin verisi profiles/<kısa-ad>/ altında (git'e girmez).
Profil sözlüğü:
  name, headline, email, phone, city, links[], summary,
  skills: [{"group", "items": []}],
  experience: [{"title", "company", "city", "dates", "bullets": [{"text", "user": bool}]}],
  education: [str], certificates: [str], languages: str, extras: [str]
"user": True → bilgiyi kullanıcı kendisi ekledi (CV'de yoktu); denetimde kaynak sayılır.
"""
import base64
import html
import io
import json
import os
import re
from datetime import datetime

from app.logger import get_logger
from app.settings import BASE_DIR

log = get_logger("cv_studio")

PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
# Şablon bilgileri: ad, kime uygun, fotoğraf kullanır mı, ATS (başvuru sistemi) dostu mu
TEMPLATE_INFO = {
    "modern": {"label": "Modern", "desc": "Renkli kenar sütunu, yuvarlak fotoğraf, iki sütun.",
               "best": "Özel sektör, teknoloji firmaları", "photo": True, "ats": False},
    "ats": {"label": "ATS uyumlu", "desc": "Sade, tek sütun, fotoğrafsız. Başvuru sistemleri en rahat bunu okur.",
            "best": "Kariyer.net / LinkedIn / şirket portalı başvuruları", "photo": False, "ats": True},
    "klasik": {"label": "Klasik", "desc": "Vesikalık fotoğraf, tırnaklı yazı tipi, resmi görünüm.",
               "best": "Kamu, savunma sanayii, bankalar", "photo": True, "ats": False},
    "zarif": {"label": "Zarif", "desc": "Üstte renkli bant ve yuvarlak fotoğraf, ferah tek sütun.",
              "best": "Genel kullanım, insan kaynakları", "photo": True, "ats": False},
    "kompakt": {"label": "Kompakt Teknik", "desc": "Mühendis tarzı: solda bölüm adı, sağda içerik; tek sayfaya sığar.",
                "best": "BT, sistem/ağ, yazılım pozisyonları", "photo": False, "ats": True},
    "yonetici": {"label": "Kurumsal Yönetici", "desc": "Ortalı başlık, 'Öne çıkan başarılar' bölümü, ağırbaşlı düzen.",
                 "best": "Kıdemli / yönetici pozisyonları, holdingler", "photo": False, "ats": True},
    "zaman": {"label": "Zaman Çizelgesi", "desc": "Deneyim dikey zaman çizgisinde, fotoğraflı, beceriler kartlarda.",
              "best": "Kariyer gelişimini göstermek isteyenler", "photo": True, "ats": False},
}
TEMPLATES = {k: f"{v['label']} — {v['desc']}" for k, v in TEMPLATE_INFO.items()}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+?90[\s-]*)?\(?0?\s*\(?5\d{2}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
CITIES = ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya", "Konya", "Eskişehir", "Kocaeli", "Adana", "Kayseri"]


# ---------------------------------------------------------------- yardımcılar
def slugify(name):
    from app.context import slugify as _slug
    s = _slug(name or "profil")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "profil"


def empty_profile():
    return {"name": "", "headline": "", "email": "", "phone": "", "city": "", "links": [], "summary": "",
            "skills": [], "experience": [], "education": [], "certificates": [], "languages": "", "extras": [],
            "qa_log": [], "template": "modern", "accent": "#1f4e79"}


def extract_text(data: bytes, filename: str) -> str:
    """PDF / DOCX / TXT → düz metin."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts += [c.text for c in row.cells]
        return "\n".join(parts)
    return data.decode("utf-8", errors="ignore")


_SPACED_HYPHEN = re.compile(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü]) - (?=[A-Za-zÇĞİÖŞÜçğıöşü])")


def fix_pdf_artifacts(text: str) -> str:
    """PDF'ten çıkarmada oluşan 'Site - to - Site' / 'Hyper - V' boşluklarını düzeltir (sayı aralıkları korunur)."""
    return _SPACED_HYPHEN.sub("-", text or "")


TYPO_HINTS = {r"(?<![Vv])\bMware\b": "VMware"}


def typo_warnings(text: str):
    """CV'de olası yazım hataları (otomatik DÜZELTİLMEZ, kullanıcıya sorulur)."""
    return [f"'{m.group(0)}' → '{fix}' olabilir" for pat, fix in TYPO_HINTS.items() for m in re.finditer(pat, text or "")]


def profile_from_text(text: str) -> dict:
    """CV metnini yapılandırılmış profile çevirir (kural tabanlı ayrıştırıcı; model gerekmez)."""
    from ai_engine.cv_builder import parse_cv, tr_title
    text = fix_pdf_artifacts(text)
    cv = parse_cv(text)
    p = empty_profile()
    p["name"], p["headline"], p["summary"] = tr_title(cv.name) if cv.name.isupper() else cv.name, cv.headline, cv.summary
    contact = " ".join(cv.contact) + "\n" + text[:1500]
    m = EMAIL_RE.search(contact)
    p["email"] = m.group(0) if m else ""
    m = PHONE_RE.search(contact)
    p["phone"] = m.group(0).strip() if m else ""
    p["city"] = next((c for c in CITIES if re.search(rf"\b{c}\b", " ".join(cv.contact))), "") or \
        next((c for c in CITIES if c in text[:600]), "")
    p["skills"] = [{"group": g, "items": list(items)} for g, items in cv.skill_groups]
    p["experience"] = [{"title": e.title, "company": e.company, "city": e.city, "dates": e.dates,
                        "bullets": [{"text": b.text, "user": False} for b in e.bullets]} for e in cv.experience]
    p["education"] = [" · ".join(x for x in lines if x) for lines in cv.education]
    p["certificates"] = [" · ".join(x for x in lines if x and x.strip().lower() != "tarih") for lines in cv.certificates]
    p["languages"] = cv.languages
    p["_warnings"] = list(cv.warnings) + typo_warnings(text)
    return p


def source_text(profile: dict, original: str = "") -> str:
    """Uydurma denetiminin kaynağı: orijinal CV + kullanıcının kendi eklediği bilgiler."""
    user = [b["text"] for e in profile.get("experience", []) for b in e.get("bullets", []) if b.get("user")]
    answers = [q.get("answer", "") for q in profile.get("qa_log", []) if q.get("answer")]  # CV Koçu cevapları
    return "\n".join([original or ""] + user + list(profile.get("extras", [])) + answers)


# ---------------------------------------------------------------- depolama (kişi başına klasör)
def _dir(slug):
    d = os.path.join(PROFILES_DIR, slug)
    os.makedirs(d, exist_ok=True)
    return d


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(s for s in os.listdir(PROFILES_DIR) if os.path.exists(os.path.join(PROFILES_DIR, s, "profile.json")))


def save_profile(slug, profile, original_text=None):
    d = _dir(slug)
    with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in profile.items() if not k.startswith("_")}, f, ensure_ascii=False, indent=2)
    if original_text is not None:
        with open(os.path.join(d, "kaynak_cv.txt"), "w", encoding="utf-8") as f:
            f.write(original_text)


def load_profile(slug):
    d = os.path.join(PROFILES_DIR, slug)
    with open(os.path.join(d, "profile.json"), encoding="utf-8") as f:
        p = {**empty_profile(), **json.load(f)}
    src = os.path.join(d, "kaynak_cv.txt")
    original = ""
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            original = f.read()
    return p, original


def save_photo(slug, data: bytes, filename: str):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    for old in ("photo.jpg", "photo.jpeg", "photo.png", "photo.webp"):
        try:
            os.remove(os.path.join(_dir(slug), old))
        except FileNotFoundError:
            pass
    with open(os.path.join(_dir(slug), f"photo{ext}"), "wb") as f:
        f.write(data)


def photo_data_uri(slug, portrait=False):
    names = (("photo_vesikalik.jpg", "jpeg"),) if portrait else ()
    for name, mime in names + (("photo.jpg", "jpeg"), ("photo.jpeg", "jpeg"), ("photo.png", "png"), ("photo.webp", "webp")):
        path = os.path.join(PROFILES_DIR, slug, name)
        if os.path.exists(path):
            return f"data:image/{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()
    return None


# ---------------------------------------------------------------- ölçülebilir madde (sayı içeren)
_NUM = re.compile(r"\d")


# ---------------------------------------------------------------- yapay zeka iyileştirme (uydurmasız)
_IMPROVE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {
            "type": "object",
            "properties": {"exp": {"type": "integer"}, "idx": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["exp", "idx", "text"], "additionalProperties": False}},
    },
    "required": ["headline", "summary", "bullets"],
    "additionalProperties": False,
}


def _profile_prompt(p):
    lines = [f"BAŞLIK: {p['headline']}", f"ÖZET: {p['summary']}"]
    for i, e in enumerate(p["experience"]):
        lines.append(f"\nDENEYİM {i}: {e['title']} — {e['company']} ({e['dates']})")
        lines += [f"  [{i}.{j}] {b['text']}" for j, b in enumerate(e["bullets"])]
    lines.append("\nBECERİLER: " + "; ".join(f"{g['group']}: {', '.join(g['items'])}" for g in p["skills"]))
    if p.get("extras"):
        lines.append("EK BİLGİLER (kullanıcı ekledi): " + "; ".join(p["extras"]))
    return "\n".join(lines)


def improve(profile: dict, original: str, target_title: str = "", model=None):
    """Başlık, özet ve maddeler için öneriler. Her öneri kaynakla karşılaştırılır; uydurma içeren REDDEDİLİR.
    Dönüş: {"accepted": [{"where","old","new"}], "rejected": [{"where","new","why"}]}"""
    from ai_engine.brain import _chat_json, fast_model
    from ai_engine.cv_builder import check_text
    from ai_engine.cv_profile import build_profile
    src = source_text(profile, original)
    try:
        years = round(build_profile(original).professional_months / 12, 1) if original else None
    except Exception:
        years = None
    system = ("Sen kıdemli bir Türk İK uzmanı ve CV editörüsün. Görevin CV'yi daha etkileyici YAZMAK, "
              "ama ASLA yeni bilgi eklememek VE ASLA bilgi silmemek. Yeni beceri, sayı, sertifika, şirket, unvan, "
              "süre UYDURMA. Maddedeki her teknoloji adını, her sayıyı ve her görevi KORU; sadece daha güçlü ve "
              "akıcı yaz. Sadece istenen JSON'u döndür.")
    user = f"""HEDEF UNVAN: {target_title or profile.get('headline') or '-'}

MEVCUT CV:
{_profile_prompt(profile)}

GÖREV:
- headline: Hedef unvana uygun, en güçlü 3 teknolojiyi içeren başlık (en fazla 120 karakter).
- summary: 3-4 cümlelik, birinci tekil şahıs, etkileyici ama ölçülü özet. SADECE CV'deki bilgiler.
- bullets: Etkisi zayıf maddeleri yeniden yaz: güçlü fiille başlasın ("Yönettim", "Kurdum", "Tasarladım"),
  varsa sayıyı öne çıkarsın, tek cümle. Maddedeki TÜM teknolojileri, sayıları ve görevleri koru — kısaltmak için
  bilgi atma. exp ve idx köşeli parantezdeki numaralar. Zaten iyi olan maddeyi listeye EKLEME. En fazla 8 madde."""
    data = _chat_json(system, user, "cv_improve", _IMPROVE_SCHEMA, temperature=0.3, model=model or fast_model())
    out = {"accepted": [], "rejected": []}

    def judge(where, old, new):
        new = (new or "").strip()
        if not new or new == old:
            return
        why = check_text(new, src, years) + info_loss(old, new)
        (out["rejected"] if why else out["accepted"]).append(
            {"where": where, "old": old, "new": new, **({"why": why} if why else {})})

    judge("headline", profile.get("headline", ""), data.get("headline"))
    judge("summary", profile.get("summary", ""), data.get("summary"))
    for b in data.get("bullets", []):
        i, j = b.get("exp"), b.get("idx")
        try:
            old = profile["experience"][i]["bullets"][j]["text"]
        except (IndexError, KeyError, TypeError):
            continue
        judge(f"exp:{i}:{j}", old, b.get("text"))
    log.info("CV iyileştirme: %d öneri kabul, %d red", len(out["accepted"]), len(out["rejected"]))
    return out


_STOP_STEMS = {"olara", "ederek", "edere", "sağla", "gerçe", "yaptı", "yöneti", "yönet", "ettim", "ederi"}


def tr_lower(t):
    return (t or "").replace("I", "ı").replace("İ", "i").lower()


def info_loss(old: str, new: str):
    """Öneri eski metindeki bilgiyi siliyor mu? (2026-11-15 canlı test: 'iyileştirme' HP Procurve, GPO, Nginx,
    SSL VPN, eğitim organizasyonu gibi bilgileri atıyordu.) Dönüş: sorun listesi."""
    from ai_engine.cv_builder import numbers_in
    from ai_engine.job_matcher import find_skills
    problems = []
    lost_sk = find_skills(old) - find_skills(new)
    if lost_sk:
        problems.append(f"bilgi kaybı (teknoloji): {', '.join(sorted(lost_sk))}")
    lost_num = numbers_in(old) - numbers_in(new)
    if lost_num:
        problems.append(f"bilgi kaybı (sayı): {', '.join(sorted(lost_num))}")
    # görev/ifade kaybı: eski metnin anlamlı kelime köklerinden (ilk 5 harf) 3+ tanesi ve %20'den fazlası yoksa
    stems = lambda t: {w[:5] for w in re.findall(r"[a-zçğıöşü]{5,}", tr_lower(t))} - _STOP_STEMS
    old_st, new_st = stems(old), stems(new)
    lost = old_st - new_st
    if old_st and len(lost) >= 3 and len(lost) / len(old_st) > 0.2:
        problems.append(f"içerik kaybı: {', '.join(sorted(lost))}…")
    if len(new) < 0.7 * len(old):
        problems.append(f"çok kısaldı ({len(old)} → {len(new)} karakter; içerik atılmış olabilir)")
    return problems


def check_text_only(new, src, years=None):
    """Uydurma denetimi (bilgi kaybı hariç)."""
    from ai_engine.cv_builder import check_text
    return check_text(new, src, years)


def apply_suggestion(profile: dict, s: dict):
    if s["where"] in ("headline", "summary"):
        profile[s["where"]] = s["new"]
    elif s["where"].startswith("exp:"):
        _, i, j = s["where"].split(":")
        profile["experience"][int(i)]["bullets"][int(j)]["text"] = s["new"]
    return profile


# ---------------------------------------------------------------- şablonlar → HTML → PDF / DOCX
def _e(s):
    return html.escape(s or "")


_BASE_CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2933; font-size: 10.5pt; line-height: 1.45; }
h1 { margin: 0; font-size: 22pt; letter-spacing: .5px; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 1.5px; margin: 16px 0 6px; padding-bottom: 3px; }
ul { margin: 4px 0 0 0; padding-left: 16px; } li { margin-bottom: 3px; }
.job { margin-bottom: 10px; page-break-inside: avoid; }
.job-head { display: flex; justify-content: space-between; gap: 8px; font-weight: 600; }
.job-sub { color: #52606d; font-size: 9.5pt; }
.chip { display: inline-block; padding: 2px 8px; margin: 2px 3px 2px 0; border-radius: 10px; font-size: 9pt; }
"""


def _experience_html(p):
    out = []
    for e in p["experience"]:
        bullets = "".join(f"<li>{_e(b['text'])}</li>" for b in e["bullets"])
        out.append(f"""<div class="job"><div class="job-head"><span>{_e(e['title'])}</span><span class="job-sub">{_e(e['dates'])}</span></div>
<div class="job-sub">{_e(e['company'])}{' · ' + _e(e['city']) if e.get('city') else ''}</div><ul>{bullets}</ul></div>""")
    return "".join(out)


def highlights(p, n=4):
    """'Öne çıkan başarılar': sayı içeren (ölçülebilir) maddeler, en çok sayı içerenler önce. Yeni bilgi üretmez."""
    found = [b["text"] for e in p.get("experience", []) for b in e.get("bullets", []) if _NUM.search(b["text"])]
    return sorted(found, key=lambda t: -len(_NUM.findall(t)))[:n]


def _list_html(items):
    return "".join(f"<li>{_e(x)}</li>" for x in items if x)


def render_html(p: dict, template="modern", photo=None, accent="#1f4e79"):
    contact = " · ".join(_e(x) for x in (p.get("email"), p.get("phone"), p.get("city")) if x)
    links = " · ".join(_e(x) for x in p.get("links", []) if x)
    extras = _list_html(p.get("extras", []))
    if template == "ats":
        skills = "".join(f"<p><b>{_e(g['group'])}:</b> {_e(', '.join(g['items']))}</p>" for g in p["skills"])
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
body {{ padding: 42px 52px; }} h2 {{ border-bottom: 1px solid #333; }} p {{ margin: 2px 0; }}</style>
<h1>{_e(p['name'])}</h1><div>{_e(p['headline'])}</div><div class="job-sub">{contact}{' · ' + links if links else ''}</div>
<h2>Özet</h2><p>{_e(p['summary'])}</p><h2>Deneyim</h2>{_experience_html(p)}
<h2>Beceriler</h2>{skills}<h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}
{'<h2>Diller</h2><p>' + _e(p['languages']) + '</p>' if p.get('languages') else ''}</html>"""

    img = f'<img src="{photo}" class="photo">' if photo else ""
    chips = "".join(f"<div class='sk-group'><div class='sk-title'>{_e(g['group'])}</div>" +
                    "".join(f"<span class='chip'>{_e(i)}</span>" for i in g["items"]) + "</div>" for g in p["skills"])
    if template == "zarif":
        skills = "".join(f"<div class='sk-group'><span class='sk-title'>{_e(g['group'])}</span> " +
                         "".join(f"<span class='chip'>{_e(i)}</span>" for i in g["items"]) + "</div>" for g in p["skills"])
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
.band {{ background: linear-gradient(120deg, {accent}, #3e7cb1); color: #fff; padding: 30px 48px; display: flex; gap: 24px; align-items: center; }}
.band .photo {{ width: 110px; height: 110px; border-radius: 50%; object-fit: cover; border: 4px solid rgba(255,255,255,.7); }}
.band h1 {{ color: #fff; }} .band .sub {{ font-size: 12.5pt; opacity: .95; }} .band .ct {{ font-size: 9pt; opacity: .9; margin-top: 4px; }}
.body {{ padding: 6px 48px 30px; }} h2 {{ color: {accent}; }} h2::after {{ content: ""; display: block; width: 42px; height: 3px; background: {accent}; margin-top: 3px; }}
.chip {{ background: #eef3f8; color: #1f2933; }} .sk-group {{ margin-bottom: 5px; }} .sk-title {{ font-weight: 600; font-size: 9.5pt; margin-right: 4px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 28px; }}</style>
<div class="band">{img}<div><h1>{_e(p['name'])}</h1><div class="sub">{_e(p['headline'])}</div>
<div class="ct">{contact}{' · ' + links if links else ''}</div></div></div>
<div class="body"><h2>Özet</h2><p>{_e(p['summary'])}</p><h2>Deneyim</h2>{_experience_html(p)}
<h2>Beceriler</h2>{skills}
<div class="two"><div><h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Diller</h2><p>' + _e(p['languages']) + '</p>' if p.get('languages') else ''}</div>
<div>{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}</div></div></div></html>"""

    if template == "klasik":
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
body {{ padding: 40px 50px; font-family: Georgia, 'Times New Roman', serif; }}
.top {{ display: flex; gap: 22px; align-items: center; border-bottom: 2px solid {accent}; padding-bottom: 14px; }}
.photo {{ width: 96px; height: 120px; object-fit: cover; border-radius: 4px; }}
h2 {{ color: {accent}; border-bottom: 1px solid #d9e2ec; }} .chip {{ background: #f0f4f8; }}
.sk-group {{ margin-bottom: 4px; }} .sk-title {{ font-weight: 600; font-size: 9.5pt; }}</style>
<div class="top">{img}<div><h1 style="color:{accent}">{_e(p['name'])}</h1><div style="font-size:12pt">{_e(p['headline'])}</div>
<div class="job-sub">{contact}</div><div class="job-sub">{links}</div></div></div>
<h2>Özet</h2><p>{_e(p['summary'])}</p><h2>Deneyim</h2>{_experience_html(p)}<h2>Beceriler</h2>{chips}
<h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}
{'<h2>Diller</h2><p>' + _e(p['languages']) + '</p>' if p.get('languages') else ''}</html>"""

    if template == "kompakt":
        def row(title, body):
            return f"<div class='row'><div class='lab'>{title}</div><div class='val'>{body}</div></div>" if body else ""
        skills = "".join(f"<div><b>{_e(g['group'])}:</b> {_e(', '.join(g['items']))}</div>" for g in p["skills"])
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
body {{ padding: 30px 40px; font-size: 9.8pt; line-height: 1.38; }}
.head {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid {accent}; padding-bottom: 8px; }}
.head h1 {{ font-size: 20pt; color: {accent}; }} .head .ct {{ text-align: right; font-size: 8.8pt; color: #52606d; }}
.row {{ display: grid; grid-template-columns: 112px 1fr; gap: 14px; padding: 9px 0; border-bottom: 1px solid #e4e7eb; }}
.lab {{ font-size: 8.6pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: {accent}; padding-top: 2px; }}
.job {{ margin-bottom: 7px; }} ul {{ margin-top: 2px; }} li {{ margin-bottom: 1px; }}</style>
<div class="head"><div><h1>{_e(p['name'])}</h1><div style="font-size:11pt">{_e(p['headline'])}</div></div>
<div class="ct">{'<br>'.join(_e(x) for x in (p.get('email'), p.get('phone'), p.get('city'), *p.get('links', [])) if x)}</div></div>
{row('Özet', _e(p['summary']))}{row('Deneyim', _experience_html(p))}{row('Beceriler', skills)}
{row('Eğitim', '<ul>' + _list_html(p['education']) + '</ul>' if p.get('education') else '')}
{row('Sertifikalar', '<ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else '')}
{row('Diller', _e(p.get('languages')))}{row('Ek Bilgiler', '<ul>' + extras + '</ul>' if extras else '')}</html>"""

    if template == "yonetici":
        hl = highlights(p)
        skills = "".join(f"<div class='sk'><div class='sk-title'>{_e(g['group'])}</div><div>{_e(', '.join(g['items']))}</div></div>"
                         for g in p["skills"])
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
body {{ padding: 44px 56px; }} .top {{ text-align: center; }}
.top h1 {{ font-family: Georgia, 'Times New Roman', serif; font-size: 25pt; letter-spacing: 3px; text-transform: uppercase; color: #102a43; }}
.top .sub {{ font-size: 11.5pt; color: {accent}; letter-spacing: 1px; margin-top: 3px; }}
.top .ct {{ font-size: 9pt; color: #52606d; margin-top: 6px; }}
.rule {{ height: 1px; background: #bcccdc; margin: 14px 0 4px; }}
h2 {{ text-align: center; color: #102a43; font-family: Georgia, serif; letter-spacing: 2.5px; }}
h2::after {{ content: ""; display: block; width: 36px; height: 2px; background: {accent}; margin: 4px auto 0; }}
.hl {{ background: #f5f7fa; border-left: 3px solid {accent}; padding: 8px 14px 8px 28px; }}
.skills {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px 18px; }} .sk-title {{ font-weight: 700; font-size: 9.2pt; color: {accent}; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 30px; }}</style>
<div class="top"><h1>{_e(p['name'])}</h1><div class="sub">{_e(p['headline'])}</div>
<div class="ct">{contact}{' · ' + links if links else ''}</div></div><div class="rule"></div>
<h2>Profil</h2><p>{_e(p['summary'])}</p>
{'<h2>Öne Çıkan Başarılar</h2><ul class="hl">' + _list_html(hl) + '</ul>' if hl else ''}
<h2>Deneyim</h2>{_experience_html(p)}<h2>Yetkinlikler</h2><div class="skills">{skills}</div>
<div class="two"><div><h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Diller</h2><p>' + _e(p['languages']) + '</p>' if p.get('languages') else ''}</div>
<div>{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}</div></div></html>"""

    if template == "zaman":
        tl = "".join(f"""<div class="ev"><div class="dot"></div><div class="when">{_e(e['dates'])}</div>
<div class="what"><b>{_e(e['title'])}</b> <span class="job-sub">— {_e(e['company'])}{' · ' + _e(e['city']) if e.get('city') else ''}</span>
<ul>{''.join(f"<li>{_e(b['text'])}</li>" for b in e['bullets'])}</ul></div></div>""" for e in p["experience"])
        cards = "".join(f"<div class='card'><div class='sk-title'>{_e(g['group'])}</div>" +
                        "".join(f"<span class='chip'>{_e(i)}</span>" for i in g["items"]) + "</div>" for g in p["skills"])
        return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
body {{ padding: 36px 46px; }}
.top {{ display: flex; gap: 22px; align-items: center; margin-bottom: 6px; }}
.top .photo {{ width: 104px; height: 104px; border-radius: 18px; object-fit: cover; }}
.top h1 {{ color: {accent}; }} .top .sub {{ font-size: 12pt; }} .top .ct {{ font-size: 9pt; color: #52606d; margin-top: 4px; }}
h2 {{ color: {accent}; }} .tl {{ position: relative; margin-left: 8px; border-left: 2px solid {accent}; padding-left: 0; }}
.ev {{ position: relative; display: grid; grid-template-columns: 118px 1fr; gap: 10px; padding: 0 0 10px 18px; page-break-inside: avoid; }}
.dot {{ position: absolute; left: -7px; top: 3px; width: 12px; height: 12px; border-radius: 50%; background: #fff; border: 3px solid {accent}; }}
.when {{ font-size: 9pt; color: #52606d; font-weight: 600; }}
.cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.card {{ border: 1px solid #e4e7eb; border-radius: 8px; padding: 7px 9px; }} .sk-title {{ font-weight: 700; font-size: 9pt; margin-bottom: 3px; }}
.chip {{ background: #eef3f8; }} .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 28px; }}</style>
<div class="top">{img}<div><h1>{_e(p['name'])}</h1><div class="sub">{_e(p['headline'])}</div>
<div class="ct">{contact}{' · ' + links if links else ''}</div></div></div>
<h2>Özet</h2><p>{_e(p['summary'])}</p><h2>Kariyer Yolculuğu</h2><div class="tl">{tl}</div>
<h2>Beceriler</h2><div class="cards">{cards}</div>
<div class="two"><div><h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Diller</h2><p>' + _e(p['languages']) + '</p>' if p.get('languages') else ''}</div>
<div>{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}</div></div></html>"""

    # modern: solda renkli kenar sütunu
    return f"""<!doctype html><html lang="tr"><meta charset="utf-8"><style>{_BASE_CSS}
.wrap {{ display: grid; grid-template-columns: 34% 66%; min-height: 297mm; }}
.side {{ background: {accent}; color: #fff; padding: 34px 22px; }}
.side h2 {{ color: #fff; border-bottom: 1px solid rgba(255,255,255,.35); }}
.side .chip {{ background: rgba(255,255,255,.16); color: #fff; }}
.sk-group {{ margin-bottom: 8px; }} .sk-title {{ font-size: 9pt; opacity: .85; margin-bottom: 2px; }}
.photo {{ width: 120px; height: 120px; border-radius: 50%; object-fit: cover; border: 3px solid rgba(255,255,255,.6);
         display: block; margin: 0 auto 14px; }}
.main {{ padding: 34px 30px; }} .main h2 {{ color: {accent}; border-bottom: 2px solid {accent}; }}
.contact div {{ font-size: 9pt; margin-bottom: 3px; word-break: break-word; }}</style>
<div class="wrap"><div class="side">{img}<h2>İletişim</h2><div class="contact">
{''.join(f'<div>{_e(x)}</div>' for x in (p.get('email'), p.get('phone'), p.get('city')) if x)}
{''.join(f'<div>{_e(x)}</div>' for x in p.get('links', []) if x)}</div>
<h2>Beceriler</h2>{chips}
{'<h2>Diller</h2><div>' + _e(p['languages']) + '</div>' if p.get('languages') else ''}
{'<h2>Sertifikalar</h2><ul>' + _list_html(p['certificates']) + '</ul>' if p.get('certificates') else ''}</div>
<div class="main"><h1 style="color:{accent}">{_e(p['name'])}</h1><div style="font-size:12.5pt;margin-top:2px">{_e(p['headline'])}</div>
<h2>Özet</h2><p>{_e(p['summary'])}</p><h2>Deneyim</h2>{_experience_html(p)}
<h2>Eğitim</h2><ul>{_list_html(p['education'])}</ul>
{'<h2>Ek Bilgiler</h2><ul>' + extras + '</ul>' if extras else ''}</div></div></html>"""


def html_to_pdf(html_str: str, path: str):
    """Başsız Chromium ile A4 PDF (Playwright zaten kurulu; ek program gerekmez)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_str, wait_until="load")
            page.pdf(path=path, format="A4", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        finally:
            browser.close()
    return path


def to_docx(p: dict, path: str):
    """ATS için sade Word dosyası (başvuru sistemleri tablo/iki sütunu iyi okumaz)."""
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    d.add_heading(p["name"], level=0)
    if p.get("headline"):
        d.add_paragraph(p["headline"])
    d.add_paragraph(" · ".join(x for x in (p.get("email"), p.get("phone"), p.get("city"), *p.get("links", [])) if x))
    for title, body in (("Özet", p.get("summary")),):
        if body:
            d.add_heading(title, level=1)
            d.add_paragraph(body)
    d.add_heading("Deneyim", level=1)
    for e in p["experience"]:
        para = d.add_paragraph()
        para.add_run(f"{e['title']} — {e['company']}").bold = True
        para.add_run(f"   {e['dates']}{' · ' + e['city'] if e.get('city') else ''}")
        for b in e["bullets"]:
            d.add_paragraph(b["text"], style="List Bullet")
    d.add_heading("Beceriler", level=1)
    for g in p["skills"]:
        para = d.add_paragraph()
        para.add_run(f"{g['group']}: ").bold = True
        para.add_run(", ".join(g["items"]))
    for title, items in (("Eğitim", p.get("education")), ("Sertifikalar", p.get("certificates")), ("Ek Bilgiler", p.get("extras"))):
        if items:
            d.add_heading(title, level=1)
            for x in items:
                d.add_paragraph(x, style="List Bullet")
    if p.get("languages"):
        d.add_heading("Diller", level=1)
        d.add_paragraph(p["languages"])
    d.save(path)
    return path


def template_photo(slug, template):
    """Şablon fotoğraf kullanıyorsa fotoğrafın data URI'si (klasik: vesikalık), yoksa None."""
    info = TEMPLATE_INFO.get(template, {})
    return photo_data_uri(slug, portrait=template == "klasik") if info.get("photo") else None


def export(slug, profile, template="modern", accent="#1f4e79"):
    """Seçili şablonla PDF + sade (ATS) Word üretir. Dönüş: {"pdf": yol, "docx": yol}"""
    out_dir = os.path.join(_dir(slug), "cikti")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = os.path.join(out_dir, f"{slugify(profile.get('name'))}_{template}_{stamp}")
    photo = template_photo(slug, template)
    pdf = html_to_pdf(render_html(profile, template, photo, accent), base + ".pdf")
    docx_path = to_docx(profile, base + ".docx")  # sade Word her şablonda (ATS sistemleri için)
    log.info("CV üretildi: %s", pdf)
    return {"pdf": pdf, "docx": docx_path}
