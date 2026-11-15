"""İlana özel CV üretici — UYDURMA YAPMADAN.

Kural: Üretilen CV'de orijinal CV'de olmayan hiçbir beceri, sayı, şirket, tarih veya
sertifika bulunamaz. Bunu modele "rica ederek" değil, kodla denetleyerek sağlarız:

1. CV kodla bölümlere ayrılır (deneyim maddeleri, beceri grupları, eğitim, sertifikalar...).
2. Model sadece şunları önerir: yeni başlık/özet, beceri sırası, madde sırası ve maddelerin
   ilana göre yeniden ifadesi. Eğitim, sertifika, tarih ve iletişim bilgisine dokunamaz.
3. Kod her önerilen cümleyi kaynağıyla karşılaştırır: kaynakta olmayan bir beceri veya sayı
   içeriyorsa öneri reddedilir ve orijinal metin kullanılır. Hiçbir madde silinmez.
4. Sonuç ATS dostu (tek sütun, tablo yok, standart başlıklar) bir .docx dosyasıdır.
"""
import json
import os
import re
from dataclasses import dataclass, field, asdict

from app.logger import get_logger
from app.settings import DOCS_DIR
from ai_engine.cv_profile import PERIOD_RE, build_profile
from ai_engine.job_matcher import find_skills, match, normalize

log = get_logger("cv_builder")

GENERATED_CV_DIR = os.path.join(DOCS_DIR, "generated_cv")
os.makedirs(GENERATED_CV_DIR, exist_ok=True)

SECTION_NAMES = {
    "kişisel bilgiler": "contact", "iletişim": "contact", "beceriler": "skills", "yetenekler": "skills",
    "diller": "languages", "hobiler": "hobbies", "özet": "summary", "profil": "summary",
    "deneyim": "experience", "iş deneyimi": "experience", "eğitim": "education",
    "sertifikalar": "certificates",
}
_DATE_LINE = re.compile(r"^(?:(?:\w+\s+)?(?:19|20)\d{2}(?:\s*[–—-].*)?|tarih)$", re.IGNORECASE)


# ------------------------------------------------------------------ CV ayrıştırma
@dataclass
class Bullet:
    id: str
    text: str


@dataclass
class Experience:
    id: str
    title: str
    company: str = ""
    city: str = ""
    dates: str = ""
    bullets: list = field(default_factory=list)


@dataclass
class ParsedCV:
    name: str = ""
    headline: str = ""
    contact: list = field(default_factory=list)
    summary: str = ""
    skill_groups: list = field(default_factory=list)   # [(grup adı, [beceriler])]
    experience: list = field(default_factory=list)
    education: list = field(default_factory=list)      # [[satırlar]]
    certificates: list = field(default_factory=list)   # [[satırlar]]
    languages: str = ""
    hobbies: str = ""
    warnings: list = field(default_factory=list)


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_title(s):
    def word(w):
        low = w.replace("I", "ı").replace("İ", "i").lower()
        return tr_upper(low[:1]) + low[1:]
    return " ".join(word(w) for w in s.split())


def _clean(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    return s.replace("( ", "(")


def _split_sections(lines):
    sections, current, header = {}, None, []
    for line in lines:
        key = SECTION_NAMES.get(line.strip().lower())
        if key:
            current = key
            sections.setdefault(key, [])
            continue
        if current is None:
            header.append(line)
        else:
            sections[current].append(line)
    return header, sections


def _find_name_and_headline(lines):
    """Tamamı büyük harf 2-4 kelimelik satır = ad; ardından gelen satır = başlık."""
    for i, line in enumerate(lines):
        words = line.split()
        if 2 <= len(words) <= 4 and line.isupper() and all(w.isalpha() for w in words):
            headline = lines[i + 1].strip() if i + 1 < len(lines) else ""
            return line.strip(), headline, i
    return "", "", -1


def _parse_skills(lines):
    # Yeni grup satır başında "Grup Adı:" ile başlar; diğer satırlar önceki grubun devamıdır
    raw_groups = []
    for line in (l.strip() for l in lines):
        if not line:
            continue
        m = re.match(r"^([^:,()]{2,40}):\s*(.*)$", line)
        if m:
            raw_groups.append([m.group(1).strip(), m.group(2)])
        elif raw_groups:
            raw_groups[-1][1] += " " + line
        else:
            raw_groups.append(["Beceriler", line])
    groups = []
    for name, body in raw_groups:
        body = _clean(body)
        items, depth, cur = [], 0, ""
        for ch in body:  # parantez içindeki virgüllerde bölme: "Windows Server (AD, GPO)"
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                items.append(cur)
                cur = ""
            else:
                cur += ch
        items.append(cur)
        items = [_clean(x) for x in items if _clean(x)]
        if items:
            groups.append((name.strip(), items))
    return groups


def _parse_experience(lines, warnings):
    entries, buffer, cur = [], [], None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("•", "-", "▪", "●")):
            if cur is None:
                continue
            cur.bullets.append(Bullet(f"{cur.id}.B{len(cur.bullets) + 1}", line.lstrip("•-▪● ").strip()))
            continue
        # Önceki madde nokta ile bitmediyse bu satır onun devamıdır
        if cur and cur.bullets and not cur.bullets[-1].text.rstrip().endswith((".", ")", "!")) and not buffer:
            cur.bullets[-1].text += " " + line
            continue
        if PERIOD_RE.search(line):
            head = buffer[-3:]
            cur = Experience(id=f"E{len(entries) + 1}", title=head[0] if head else "",
                             company=head[1] if len(head) > 1 else "", city=head[2] if len(head) > 2 else "",
                             dates=line)
            entries.append(cur)
            buffer = []
            continue
        buffer.append(line)
    for e in entries:
        for b in e.bullets:
            b.text = _clean(b.text)
    if not entries:
        warnings.append("Deneyim bölümü ayrıştırılamadı.")
    return entries


def _group_by_date(lines, warnings, label):
    groups, cur = [], []
    for line in (l.strip() for l in lines):
        if not line:
            continue
        cur.append(line)
        if _DATE_LINE.match(line) or PERIOD_RE.search(line):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    for g in groups:
        if g and g[-1].lower() == "tarih":
            warnings.append(f"{label}: '{g[0]}' için tarih yerine 'Tarih' yazıyor (orijinal CV'de yer tutucu). "
                            "Üretilen CV'de tarih boş bırakıldı; Cv.pdf'i düzeltmen iyi olur.")
            g.pop()
    return groups


def parse_cv(cv_text):
    lines = [l.rstrip() for l in cv_text.splitlines()]
    header, sec = _split_sections(lines)
    cv = ParsedCV()

    # Ad/başlık sayfa düzenine göre herhangi bir bölümün sonunda olabilir (iki sütunlu PDF)
    for key in [None] + list(sec):
        block = header if key is None else sec[key]
        name, headline, idx = _find_name_and_headline(block)
        if name:
            cv.name, cv.headline = name, headline
            del block[idx:idx + 2]
            break

    cv.contact = [_clean(l) for l in sec.get("contact", []) if l.strip()]
    cv.summary = _clean(" ".join(sec.get("summary", [])))
    cv.skill_groups = _parse_skills(sec.get("skills", []))
    cv.experience = _parse_experience(sec.get("experience", []), cv.warnings)
    cv.education = _group_by_date(sec.get("education", []), cv.warnings, "Eğitim")
    cv.certificates = _group_by_date(sec.get("certificates", []), cv.warnings, "Sertifikalar")
    cv.languages = _clean(" ".join(sec.get("languages", [])))
    cv.hobbies = _clean(" ".join(sec.get("hobbies", [])))
    if not cv.name:
        cv.warnings.append("Ad-soyad satırı bulunamadı.")
    return cv


# ------------------------------------------------------------------ Uydurma denetimi
def numbers_in(text):
    """'18.000' → '18000', '52'den' → '52'. Tarihler dahil tüm sayılar."""
    return {n.replace(".", "").replace(",", "") for n in re.findall(r"\d[\d.,]*\d|\d", normalize(text))}


# Beceri sözlüğünde olmayan ama sık uydurulan iddialar: metinde geçiyorsa kaynakta da geçmeli
CLAIM_WORDS = [
    "otomasyon", "automation", "lider", "liderlik", "ekip yönet", "takım yönet", "proje yönet",
    "yönetici olarak", "uzmanı", "sertifikalı", "devops", "bulut", "cloud", "aws", "azure", "kubernetes",
    "docker", "yapay zeka", "makine öğren", "scrum", "agile", "itil", "iso 27001", "kvkk", "gdpr",
]
_YEARS_CLAIM = re.compile(r"(\d+(?:[.,]\d+)?)\s*\+?\s*(?:yıl|yil|sene|years?)", re.IGNORECASE)


def check_text(new, source, cv_years=None):
    """Yeni metin kaynakta olmayan beceri/sayı içeriyor mu? Dönüş: sorun listesi (boş = temiz)."""
    problems = []
    extra_skills = find_skills(new) - find_skills(source)
    if extra_skills:
        problems.append(f"kaynakta olmayan beceri: {', '.join(sorted(extra_skills))}")
    extra_nums = numbers_in(new) - numbers_in(source)
    if extra_nums:
        problems.append(f"kaynakta olmayan sayı: {', '.join(sorted(extra_nums))}")
    new_low, src_low = normalize(new).lower(), normalize(source).lower()
    claims = [w for w in CLAIM_WORDS if w in new_low and w not in src_low]
    if claims:
        problems.append(f"kaynakta olmayan iddia: {', '.join(claims)}")
    if cv_years is not None:
        for m in _YEARS_CLAIM.finditer(new):
            if float(m.group(1).replace(",", ".")) > cv_years:
                problems.append(f"deneyim abartısı: '{m.group(0)}' (gerçek {cv_years} yıl)")
    return problems


# ------------------------------------------------------------------ Model önerisi
_TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "skill_group_order": {"type": "array", "items": {"type": "string"}},
        "skill_priority": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"source": {"type": "string"}, "text": {"type": "string"}},
                            "required": ["source", "text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "bullets"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "summary", "skill_group_order", "skill_priority", "experience"],
    "additionalProperties": False,
}


def _cv_as_prompt(cv: ParsedCV):
    out = [f"BAŞLIK: {cv.headline}", f"ÖZET: {cv.summary}", "BECERİ GRUPLARI:"]
    out += [f"  - {name}: {', '.join(items)}" for name, items in cv.skill_groups]
    out.append("DENEYİM:")
    for e in cv.experience:
        out.append(f"  [{e.id}] {e.title} — {e.company} ({e.dates})")
        out += [f"     [{b.id}] {b.text}" for b in e.bullets]
    return "\n".join(out)


def _ask_model(cv, job_title, company, job_desc, facts, model=None):
    from ai_engine.brain import _chat_json, JOB_DESC_MAX_CHARS  # döngüsel içe aktarmayı önler
    user = f"""Hedef ilan: {job_title} — {company}

İLAN METNİ:
{(job_desc or '')[:JOB_DESC_MAX_CHARS]}

ADAYIN CV'Sİ (her maddenin kimliği köşeli parantez içinde):
{_cv_as_prompt(cv)}

İlanda geçen ve CV'de OLAN beceriler (öne çıkar): {', '.join(facts.matched_required + facts.matched_preferred) or '-'}
İlanda geçen ama CV'de OLMAYAN beceriler (ASLA yazma, ima etme): {', '.join(facts.missing_required + facts.missing_preferred) or '-'}

GÖREV: Bu CV'yi bu ilana göre düzenle. YALAN SÖYLEME — sadece CV'de yazanı yeniden düzenle.
- headline: İlana uygun kısa unvan satırı (CV'deki mevcut rollere dayansın).
- summary: 3-4 cümlelik Türkçe özet. Sadece CV'deki bilgiler; CV'de olmayan sayı, yıl, beceri yazma.
- skill_group_order: beceri grup adlarının ilana göre önem sırası (adları aynen yaz).
- skill_priority: ilan için en önemli 8-15 beceri, CV'deki yazılışıyla aynen.
- experience: her deneyim [E..] için TÜM maddeler, ilana en uygun olan önce.
    source = orijinal madde kimliği (ör. E1.B3); text = maddenin ilana göre YENİDEN YAZILMIŞ hali.
    Her maddeyi gerçekten yeniden yaz, aynen kopyalama:
      * İlanla ilgili teknolojiyi/sonucu cümlenin BAŞINA al.
      * Güçlü bir eylemle bitir (yönettim, kurdum, yapılandırdım, güçlendirdim...).
      * İlandaki ifadeleri kullan, AMA sadece o maddede zaten yazan teknoloji/iş için.
      * Kısa tut: en fazla 25 kelime. İlanla alakasız ayrıntıyı at.
      * Maddedeki TÜM SAYILARI aynen koru (18.000 kullanıcı, 52 VM gibi) — bunlar en güçlü kanıttır.
    YASAK: o maddede yazmayan sayı, teknoloji, ürün, sertifika veya iddia (otomasyon, liderlik vb.) eklemek.
    Örnek — orijinal: "Yerel ağ altyapısında switch konfigürasyonları ve alt yapı kurulumlarını gerçekleştirdim."
             iyi: "Switch konfigürasyonu ve yerel ağ altyapı kurulumlarını gerçekleştirdim."
             KÖTÜ: "Cisco switch'lerde VLAN ve OSPF yapılandırdım." (maddede Cisco/VLAN/OSPF yok)
    Her maddeyi bir kez kullan."""
    return _chat_json(
        system="Sen dürüst bir CV editörüsün. Bilgi eklemez, sadece mevcut bilgiyi ilana göre öne çıkarırsın. Sadece JSON döndürürsün.",
        user=user, schema_name="cv_tailor", schema=_TAILOR_SCHEMA, temperature=0.4, model=model,
    )


# ------------------------------------------------------------------ Öneriyi doğrulayıp uygula
def apply_suggestion(cv: ParsedCV, data: dict, cv_text: str, cv_years: float):
    """Model önerisini denetleyerek uygular. Dönüş: (yeni ParsedCV, rapor)."""
    report = {"accepted": [], "rejected": [], "notes": list(cv.warnings)}
    out = ParsedCV(**{k: v for k, v in asdict(cv).items() if k not in ("experience", "skill_groups")})
    out.skill_groups = [(n, list(i)) for n, i in cv.skill_groups]

    def take(label, new, source, original, keep_numbers=False):
        new = _clean(new or "")
        if not new:
            return original
        problems = check_text(new, source, cv_years)
        lost = numbers_in(source) - numbers_in(new) if keep_numbers else set()
        if lost:  # "18.000 kullanıcı" gibi ölçülebilir başarılar CV'nin en güçlü kısmı; silinemez
            problems.append(f"orijinaldeki sayı silindi: {', '.join(sorted(lost))}")
        if problems:
            report["rejected"].append({"where": label, "text": new, "why": problems})
            return original
        if new != original:
            report["accepted"].append(label)
        return new

    out.headline = take("Başlık", data.get("headline"), cv_text, cv.headline)
    out.summary = take("Özet", data.get("summary"), cv_text, cv.summary)

    # Beceriler: sadece sıralama. Grup içinde öncelikli beceriler başa alınır, hiçbiri eklenmez/silinmez.
    order = [n.strip().lower() for n in data.get("skill_group_order", [])]
    out.skill_groups.sort(key=lambda g: order.index(g[0].lower()) if g[0].lower() in order else len(order))
    prio = [p.strip().lower() for p in data.get("skill_priority", [])]

    def rank(item):
        low = item.lower()
        hits = [i for i, p in enumerate(prio) if p and (p == low or p in low)]
        return hits[0] if hits else len(prio)
    out.skill_groups = [(n, sorted(items, key=rank)) for n, items in out.skill_groups]

    # Deneyim: sıralama + maddeleri yeniden ifade; kaynağı olmayan madde eklenemez, hiçbiri silinmez.
    # Maddeler kaynak kimliğinden (E1.B3 → E1) gruplanır; model deneyim kimliğini yanlış yazsa da
    # ("E1.B1", "[E1]") öneri kaybolmaz.
    suggested = {}
    for e in data.get("experience", []):
        for s in e.get("bullets", []):
            src = re.sub(r"[\[\]\s]", "", s.get("source") or "")
            s = dict(s, source=src)
            suggested.setdefault(src.split(".")[0], []).append(s)
    for e in cv.experience:
        by_id = {b.id: b for b in e.bullets}
        used, bullets = set(), []
        for s in suggested.get(e.id, []):
            src = by_id.get((s.get("source") or "").strip())
            if not src or src.id in used:
                if s.get("text"):
                    report["rejected"].append({"where": e.id, "text": s.get("text"),
                                               "why": ["geçersiz/tekrar eden kaynak madde"]})
                continue
            used.add(src.id)
            bullets.append(Bullet(src.id, take(f"{e.company or e.title} / {src.id}", s.get("text"), src.text, src.text,
                                         keep_numbers=True)))
        bullets += [b for b in e.bullets if b.id not in used]  # modelin atladıkları aynen eklenir
        out.experience.append(Experience(e.id, e.title, e.company, e.city, e.dates, bullets))
    known = {e.id for e in cv.experience}
    for key, items in suggested.items():
        if key not in known:
            report["rejected"] += [{"where": key or "?", "text": s.get("text", ""),
                                    "why": ["CV'de olmayan madde kimliği"]} for s in items if s.get("text")]
    return out, report


# ------------------------------------------------------------------ DOCX çıktı
def write_docx(cv: ParsedCV, path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(1.6)
        s.left_margin = s.right_margin = Cm(1.8)
    base = doc.styles["Normal"]
    base.font.name = "Calibri"
    base.font.size = Pt(10.5)
    base.paragraph_format.space_after = Pt(2)

    def heading(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(tr_upper(text))
        r.bold = True
        r.font.size = Pt(12)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(tr_title(cv.name) if cv.name.isupper() else cv.name)
    r.bold = True
    r.font.size = Pt(18)
    if cv.headline:
        p = doc.add_paragraph(cv.headline)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cv.contact:
        p = doc.add_paragraph(" | ".join(cv.contact))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if cv.summary:
        heading("Özet")
        doc.add_paragraph(cv.summary)

    if cv.skill_groups:
        heading("Beceriler")
        for name, items in cv.skill_groups:
            p = doc.add_paragraph()
            p.add_run(f"{name}: ").bold = True
            p.add_run(", ".join(items))

    if cv.experience:
        heading("Deneyim")
        for e in cv.experience:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.add_run(e.title).bold = True
            meta = " | ".join(x for x in (e.company, e.city, e.dates) if x)
            if meta:
                doc.add_paragraph().add_run(meta).italic = True
            for b in e.bullets:
                doc.add_paragraph(b.text, style="List Bullet")

    for title, groups in (("Eğitim", cv.education), ("Sertifikalar", cv.certificates)):
        if groups:
            heading(title)
            for g in groups:
                p = doc.add_paragraph()
                p.add_run(g[0]).bold = True
                if len(g) > 1:
                    p.add_run(" — " + " | ".join(g[1:]))

    if cv.languages:
        heading("Diller")
        doc.add_paragraph(cv.languages)
    if cv.hobbies:
        heading("Hobiler")
        doc.add_paragraph(cv.hobbies)
    doc.save(path)
    return path


def docx_text(path):
    from docx import Document
    return "\n".join(p.text for p in Document(path).paragraphs)


# ------------------------------------------------------------------ Ana giriş
def build_tailored_cv(job_id, job_title, company, job_desc, model=None):
    """İlana özel CV üretir. Dönüş: {"path", "report"}. Hata durumunda AIError fırlatır."""
    from ai_engine.brain import read_cv_text, AIError, _safe_filename
    cv_text = read_cv_text()
    if not cv_text:
        raise AIError("CV bulunamadı (documents/Cv.pdf)")
    parsed = parse_cv(cv_text)
    if not parsed.experience:
        raise AIError("CV'nin deneyim bölümü okunamadı; ilana özel CV üretilemiyor.")
    profile = build_profile(cv_text)
    facts = match(f"{job_title}\n{job_desc or ''}", cv_text, profile)

    data = _ask_model(parsed, job_title, company, job_desc, facts, model=model)
    tailored, report = apply_suggestion(parsed, data, cv_text, profile.professional_years)

    path = os.path.join(GENERATED_CV_DIR, f"{job_id}_{_safe_filename(company)}_CV.docx")
    write_docx(tailored, path)

    # Son güvenlik ağı: tüm belgede orijinalde olmayan beceri/sayı var mı?
    final_problems = check_text(docx_text(path), cv_text)
    if final_problems:
        os.remove(path)
        raise AIError(f"Üretilen CV son denetimden geçemedi ({'; '.join(final_problems)}); dosya silindi.")

    report["missing_in_cv"] = facts.missing_required + facts.missing_preferred
    with open(path.replace(".docx", "_rapor.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "title": job_title, "company": company, "model_raw": data, **report},
                  f, ensure_ascii=False, indent=2)
    log.info("İlan #%s için özel CV üretildi: %s (kabul %d, red %d)", job_id, path,
             len(report["accepted"]), len(report["rejected"]))
    return {"path": path, "report": report}
