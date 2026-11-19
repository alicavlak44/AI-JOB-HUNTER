"""CV Koçu: CV'yi okur, eksikleri bulur, KULLANICIYA soru sorar; cevaplara göre CV'yi günceller.

Akış:  build_questions() → kullanıcı cevaplar → propose_edits() → kullanıcı onaylar → apply_edits()
       → (isterse) yeni tur: daha önce sorulanlar tekrar sorulmaz.

Kural: CV'ye giren her yeni bilgi ya orijinal CV'de ya da kullanıcının bu cevaplarında olmalı. Yapay zekânın
önerdiği her değişiklik cv_builder.check_text ile kaynağa (CV + cevaplar) karşı denetlenir; uydurma reddedilir.
Model (LM Studio) kapalıysa sorular kural tabanlı üretilir ve cevaplar olduğu gibi CV'ye eklenir.

Soru:   {"key", "section", "question", "why", "example", "kind": text|yesno, "source": kural|yapay zekâ, ["fix"]}
Bölüm:  headline | summary | skills | certificates | languages | education | extras | typo | exp:N
Düzenleme: {"where", "old", "new", "label", "key"}  where: headline | summary | languages | exp:N:M | exp:N:+ |
           skills:+ | certificates:+ | education:+ | extras:+ | typo
"""
import hashlib
import re
from datetime import date

from ai_engine import cv_studio as cs
from app.logger import get_logger

log = get_logger("cv_interview")

MAX_QUESTIONS = 10
AI_TIMEOUT = 180  # sn: koç ekranında en fazla bu kadar beklenir, sonra kural tabanlı sorulara / cevaplara geçilir
YES = {"evet", "e", "yes", "y", "olur", "tamam", "düzelt", "duzelt", "✓"}
# "Bilgi yok" anlamındaki cevaplar: soru atlanmış sayılır, CV'ye bir şey eklenmez
NON_ANSWERS = {"yok", "hayır", "hayir", "bilmiyorum", "hatırlamıyorum", "hatirlamiyorum", "emin değilim", "yok.",
               "-", "—", "geç", "gec", "pas", "boş", "bos", "no", "none", "n/a", "yok maalesef", "maalesef yok"}
_SECTION_RE = re.compile(r"^(headline|summary|skills|certificates|languages|education|extras|exp:\d+)$")
# Yapay zekâ sorularında istenmeyenler: yazım hatasını tekrar sorma, geleceği/varsayımı sorma, suçlayıcı dil, çok parçalı soru
_BAD_Q = [r"yazım hata", r"mware", r"\w+(ecek|acak)s[iı]n[iı]z", r"\biddia", r"\bne zaman bitecek", r"hen[üu]z almad"]
_NUM = re.compile(r"\d")


# ---------------------------------------------------------------- yardımcılar
def _field():
    """Etkin kullanıcının alanı (it / ik / genel); bağlam yoksa 'genel'."""
    try:
        from app import context
        return context.field() or "genel"
    except Exception:
        return "genel"


def asked_keys(profile):
    """Daha önce sorulmuş (cevaplanmış ya da atlanmış) soruların anahtarları."""
    return {q.get("key") for q in profile.get("qa_log", [])}


def _q(key, section, question, why, example="", kind="text", **extra):
    return {"key": key, "section": section, "question": question, "why": why, "example": example,
            "kind": kind, "source": "kural", **extra}


def _sentence(text):
    """Cevabı CV maddesine çevirir: baş harf büyük, sonda nokta."""
    t = re.sub(r"\s+", " ", (text or "").strip()).rstrip(".")
    return (t[:1].upper() + t[1:] + ".") if t else ""


def _split_list(text):
    return [x.strip(" .") for x in re.split(r"[,;\n]", text or "") if x.strip(" .")]


def cv_years(original):
    from ai_engine.cv_profile import build_profile
    try:
        return round(build_profile(original).professional_months / 12, 1) if original else None
    except Exception:
        return None


# ---------------------------------------------------------------- 1) sorular
def rule_questions(profile, original=""):
    """Model gerektirmeyen, CV'nin ölçülebilir eksiklerinden çıkan sorular (öncelik sırasıyla)."""
    p, out = profile, []
    for pat, fix in cs.TYPO_HINTS.items():
        for m in re.finditer(pat, cs.source_text(p, original)):
            out.append(_q(f"typo:{m.group(0)}", "typo", f"CV'de '{m.group(0)}' yazıyor. '{fix}' olarak düzeltilsin mi?",
                          "Yazım hatası işverende özensizlik izlenimi bırakır.", "Evet / Hayır", "yesno",
                          wrong=m.group(0), fix=fix))
            break
    if not p.get("headline"):
        out.append(_q("headline", "headline", "Hangi unvanla iş arıyorsunuz?",
                      "Başlık, işverenin ilk okuduğu satırdır.", "Ağ ve Sistem Yöneticisi"))
    for i, e in enumerate(p.get("experience", [])[:3]):
        where = f"'{e.get('title')}' ({e.get('company')})"
        if len(e.get("bullets", [])) < 2:
            out.append(_q(f"tasks:{i}", f"exp:{i}", f"{where} işinde yaptığınız 2-3 ana görevi yazar mısınız?",
                          "Her işte en az 2 madde olmalı; tek maddelik iş zayıf görünür.",
                          "Sunucu yedeklemelerini yönettim; 120 kullanıcıya destek verdim"))
        if not any(_NUM.search(b["text"]) for b in e.get("bullets", [])):
            out.append(_q(f"num:{i}", f"exp:{i}", f"{where} işinde ölçülebilir bir sonucunuz var mı? "
                          "(kaç kullanıcı, sunucu, cihaz, şube; yüzde kaç iyileşme, ne kadar süre...)",
                          "Sayı içeren maddeler, sayısız olanlardan çok daha inandırıcıdır.",
                          "Yaklaşık 300 kullanıcıya destek verdim; arıza çözüm süresini 2 güne indirdim"))
    if any(re.search(r"\btarih\b", c, re.I) for c in p.get("certificates", [])) or not p.get("certificates"):
        out.append(_q("certificates", "certificates",
                      "Sahip olduğunuz sertifikaları ve alındıkları yılı yazar mısınız? (yoksa boş bırakın)",
                      "Bazı sertifikalarda tarih eksik ya da hiç sertifika yok.", "CCNA – 2024; Fortinet NSE 4 – 2025"))
    from ai_engine.cv_audit import _LANG_LEVEL, _YEAR
    if not p.get("languages"):
        out.append(_q("languages", "languages", "Hangi yabancı dilleri, hangi seviyede biliyorsunuz?",
                      "Büyük şirketler ve savunma sanayii dil bilgisini sorar.", "İngilizce – orta (B1)"))
    elif not _LANG_LEVEL.search(p["languages"]):
        out.append(_q("langlevel", "languages", f"CV'de '{p['languages']}' yazıyor. Seviyeniz nedir?",
                      "Seviyesiz dil bilgisi işverene bir şey söylemez.", "B1 / orta — okuduğumu anlarım, teknik doküman okurum"))
    for j, c in enumerate(p.get("certificates", [])):
        if not _YEAR.search(c) and not re.search(r"\btarih\b", c, re.I):
            out.append(_q(f"certyear:{j}", f"cert:{j}", f"'{c.split(' · ')[0]}' sertifikasını hangi yıl aldınız?",
                          "Tarihsiz sertifika eski ya da yarım kalmış gibi görünür.", "2023"))
    links = " ".join(p.get("links", [])).lower()
    if "linkedin" not in links:
        out.append(_q("linkedin", "links", "LinkedIn profil adresiniz nedir?",
                      "İK, CV'den sonra ilk LinkedIn'e bakar.", "linkedin.com/in/ad-soyad"))
    if _field() == "it" and not any(k in links for k in ("github", "gitlab", "portfolio", "portfolyo", "blog")):
        out.append(_q("github", "links", "Paylaşabileceğiniz bir GitHub / portfolyo / blog adresiniz var mı? (yoksa boş bırakın)",
                      "BT pozisyonlarında betik, otomasyon ya da laboratuvar çalışmalarınızı gösterir.", "github.com/kullanici-adi"))
    if len(p.get("summary", "")) < 250:
        out.append(_q("summary", "summary", "Kendinizi 2-3 cümleyle nasıl tanıtırsınız? İşverene en çok neyi vurgulamak istersiniz?",
                      "Özet kısa; işverenin ilk 6 saniyede okuduğu yer.", ""))
    if sum(len(g["items"]) for g in p.get("skills", [])) < 10:
        out.append(_q("skills", "skills", "CV'de yazmayan ama işte düzenli kullandığınız araç ve teknolojiler var mı? (virgülle)",
                      "İşe alımcılar beceri listesine göre arama yapar.", "Zabbix, Veeam, PowerShell"))
    extras = " ".join(p.get("extras", [])).lower()
    if not any(k in extras for k in ("ehliyet", "sürücü", "askerlik", "muaf", "tecil")):
        out.append(_q("extras", "extras", "Sürücü belgeniz ve askerlik durumunuz nedir? (CV'de görünmesini istemiyorsanız boş bırakın)",
                      "Türkiye'de işverenler bunları sık sorar; CV'de yazması soruyu ortadan kaldırır.",
                      "B sınıfı ehliyet; askerlik yapıldı"))
    return out


_Q_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "maxItems": 6, "items": {
        "type": "object",
        "properties": {"section": {"type": "string"}, "question": {"type": "string"}, "why": {"type": "string"},
                       "example": {"type": "string"}},
        "required": ["section", "question", "why", "example"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}


def ai_questions(profile, original="", target_title="", job_text="", previous=(), model=None):
    """Yapay zekâ CV'yi bir İK uzmanı gözüyle okur ve CV'yi güçlendirecek EKSİK bilgileri sorar (bilgi üretmez)."""
    from ai_engine.brain import _chat_json, fast_model
    system = ("Sen Türkiye'de çalışan kıdemli bir İK uzmanı ve kariyer koçusun. Adayın CV'sini okuyup, CV'yi "
              "güçlendirmek için ADAYA SORULAR soracaksın. Asla bilgi uydurma, cevap önerme; sadece soru sor. "
              "Sorular kısa, tek konulu, samimi ve Türkçe olsun. Sadece istenen JSON'u döndür.")
    prev = "\n".join(f"- {q}" for q in previous) or "-"
    from ai_engine import cv_audit
    gaps = "\n".join(f"- {c['area']}: {c['msg']}"
                     for c in cv_audit.failing(cv_audit.audit(profile, job_text, field=_field()))[:8]) or "-"
    first = (profile.get("experience") or [{}])[0]
    example_job = first.get("company") or "Son"
    user = f"""HEDEF UNVAN: {target_title or profile.get('headline') or '-'}
{('HEDEF İLAN (özet):' + chr(10) + job_text[:2500]) if job_text else ''}

CV:
{cs._profile_prompt(profile)}
EĞİTİM: {'; '.join(profile.get('education', []))}
SERTİFİKALAR: {'; '.join(profile.get('certificates', []))}
DİLLER: {profile.get('languages') or '-'}

DAHA ÖNCE SORULANLAR (bunları tekrar sorma):
{prev}

KONTROL LİSTESİNDE EKSİK ÇIKANLAR (öncelik ver):
{gaps}

GÖREV: En fazla 6 soru üret. İşverenin bu CV'de ARAYIP BULAMAYACAĞI şeyleri sor: ölçülebilir sonuçlar (sayı, yüzde,
süre), sorumluluğun kapsamı (kaç kişi/cihaz/şube), kullanılan araçlar, çözülen önemli bir sorun, hedef ilan için
eksik görünen beceriler (adayın gerçekten bilip bilmediğini sor). CV'de zaten yazan şeyi sorma.
KURALLAR: Her soru TEK soru işareti, en fazla 2 satır. Geçmişi sor, geleceği sorma. Varsayımda bulunma ve
suçlama ("iddia ediyorsunuz") yapma. Yazım hatalarını sorma (onları sistem soruyor).
İYİ ÖRNEK: "{example_job} işinizde bu sistemleri kaç kullanıcı / kaç şube için yönettiniz?"
İYİ ÖRNEK: "SIEM tarafında hangi aracı kullandınız (Wazuh, Graylog, QRadar...)?"
KÖTÜ ÖRNEK: "Mezun olmadan önce hangi projelerde liderlik edeceksiniz?" (gelecek + varsayım)
KÖTÜ ÖRNEK: "Kesintiyi nasıl tespit ettiniz ve kaç dakikada çözdünüz?" (iki soru bir arada)
section: hangi bölümü güncelleyeceği — headline, summary, skills, certificates, languages, education, extras
veya bir deneyim için "exp:N" (N = DENEYİM numarası). why: bu sorunun CV'ye katkısı (tek cümle).
example: adayın cevabına örnek biçim (kısa)."""
    data = _chat_json(system, user, "cv_questions", _Q_SCHEMA, temperature=0.4, model=model or fast_model(),
                      timeout=AI_TIMEOUT, max_tokens=1200)
    out, n_exp = [], len(profile.get("experience", []))  # noqa: E501
    for k, q in enumerate(data.get("questions", [])):
        sec = (q.get("section") or "").strip().lower()
        if not _SECTION_RE.match(sec) or (sec.startswith("exp:") and int(sec[4:]) >= n_exp):
            sec = "extras"
        text = (q.get("question") or "").strip()
        if question_problems(text):
            log.info("Zayıf soru elendi (%s): %s", ", ".join(question_problems(text)), text)
            continue
        out.append({"key": "ai:" + hashlib.md5(text.encode()).hexdigest()[:10], "section": sec, "question": text,
                    "why": (q.get("why") or "").strip(), "example": (q.get("example") or "").strip(),
                    "kind": "text", "source": "yapay zekâ"})
    return out


def question_problems(text):
    """Yapay zekânın sorusu kullanıcıya gösterilecek kadar iyi mi? Dönüş: sorun listesi (boş = iyi)."""
    t = cs.tr_lower(text or "")
    probs = []
    if len(t) < 12:
        probs.append("çok kısa")
    if len(t) > 220:
        probs.append("çok uzun")
    if t.count("?") > 1:
        probs.append("birden çok soru")
    probs += [f"istenmeyen ifade: {pat}" for pat in _BAD_Q if re.search(pat, t)]
    return probs


def build_questions(profile, original="", target_title="", job_text="", use_ai=True, model=None):
    """Kural + yapay zekâ soruları; daha önce sorulanlar elenir. Dönüş: (sorular, yapay_zeka_hatası|None)."""
    done = asked_keys(profile)
    rules = [q for q in rule_questions(profile, original) if q["key"] not in done]
    ai, err = [], None
    if use_ai:
        try:
            prev = [q.get("question", "") for q in profile.get("qa_log", [])] + [q["question"] for q in rules]
            ai = ai_questions(profile, original, target_title, job_text, prev, model=model)
        except Exception as e:  # model kapalı / geçersiz JSON: kural soruları yine çalışır
            err = str(e)
            log.warning("Yapay zekâ soruları üretilemedi: %s", e)
    per_section = {}
    out, seen = [], set()
    for q in rules[:6] + ai + rules[6:]:  # en önemli kural soruları önce, sonra yapay zekâ, sonra kalanlar
        norm = re.sub(r"\W+", " ", q["question"].lower()).strip()
        if q["key"] in done or norm in seen or per_section.get(q["section"], 0) >= 2:
            continue
        seen.add(norm)
        per_section[q["section"]] = per_section.get(q["section"], 0) + 1
        out.append(q)
    return out[:MAX_QUESTIONS], err


# ---------------------------------------------------------------- 2) cevaplardan düzenleme önerileri
_EDIT_SCHEMA = {
    "type": "object",
    "properties": {"edits": {"type": "array", "items": {
        "type": "object",
        "properties": {"where": {"type": "string"}, "text": {"type": "string"}, "answer": {"type": "integer"}},
        "required": ["where", "text", "answer"], "additionalProperties": False}}},
    "required": ["edits"], "additionalProperties": False,
}
# Yapay zekânın yazabileceği hedefler ("typo" YOK: yazım düzeltmesi sadece kullanıcının Evet cevabıyla, kuraldan gelir)
_WHERE_RE = re.compile(r"^(headline|summary|languages|exp:\d+:(\d+|\+)|certificates:\d+|"
                       r"(skills|certificates|education|extras|links):\+)$")


def _old_value(profile, where):
    if where in ("headline", "summary", "languages"):
        return profile.get(where, "")
    m = re.match(r"certificates:(\d+)$", where)
    if m:
        certs = profile.get("certificates", [])
        return certs[int(m.group(1))] if int(m.group(1)) < len(certs) else None
    m = re.match(r"exp:(\d+):(\d+)$", where)
    if m:
        try:
            return profile["experience"][int(m.group(1))]["bullets"][int(m.group(2))]["text"]
        except (IndexError, KeyError):
            return None
    m = re.match(r"exp:(\d+):\+$", where)
    if m and int(m.group(1)) >= len(profile.get("experience", [])):
        return None
    if where == "typo":
        return None
    return ""


def _label(profile, where):
    names = {"headline": "Başlık", "summary": "Özet", "languages": "Diller", "skills:+": "Yeni beceriler",
             "certificates:+": "Yeni sertifika", "education:+": "Eğitim", "extras:+": "Ek bilgi", "typo": "Yazım düzeltmesi",
             "links:+": "Bağlantı"}
    if where.startswith("certificates:"):
        return "Sertifika yılı"
    if where in names:
        return names[where]
    m = re.match(r"exp:(\d+):(\d+|\+)$", where)
    if m:
        e = profile["experience"][int(m.group(1))]
        return f"{e.get('title')} — " + ("yeni madde" if m.group(2) == "+" else f"{int(m.group(2)) + 1}. madde")
    return where


def is_real_answer(answer):
    a = re.sub(r"\s+", " ", (answer or "").strip().lower()).strip(" .!")
    return bool(a) and a not in NON_ANSWERS


_LANG_NAMES = r"(ingilizce|almanca|fransızca|arapça|rusça|ispanyolca|italyanca|japonca|çince|english|german)"


def merge_language(old, answer):
    """'İngilizce, Almanca – A2' + 'İngilizce C1' → 'İngilizce C1, Almanca – A2' (diğer diller korunur)."""
    if not old:
        return answer
    parts = [x.strip() for x in re.split(r"[,;]", old) if x.strip()]
    names = set(re.findall(_LANG_NAMES, cs.tr_lower(answer)))
    kept = [x for x in parts if not (set(re.findall(_LANG_NAMES, cs.tr_lower(x))) & names)]
    return ", ".join([answer] + kept) if len(kept) < len(parts) else ", ".join(parts + [answer])


def fallback_edits(profile, q, answer):
    """Model olmadan: cevabı kullanıcının kendi sözleriyle ilgili bölüme ekler."""
    a = (answer or "").strip()
    sec = q["section"]
    if not a:
        return []
    if sec == "typo":
        return [{"where": "typo", "old": q.get("wrong", ""), "new": q.get("fix", "")}] if a.lower() in YES else []
    if sec == "headline":
        return [{"where": sec, "old": profile.get(sec, ""), "new": a}]
    if sec == "languages":
        old = profile.get("languages", "")
        has_lang = re.search(r"(ingilizce|almanca|fransızca|arapça|rusça|ispanyolca|italyanca|japonca|çince|english|german)",
                             cs.tr_lower(a))
        return [{"where": "languages", "old": old, "new": merge_language(old, a) if has_lang else
                 (f"{old} – {a}" if old else a)}]
    if sec == "links":
        return [{"where": "links:+", "old": "", "new": x} for x in _split_list(a) if "." in x]
    m = re.match(r"cert:(\d+)$", sec)
    if m:
        j = int(m.group(1))
        old = profile.get("certificates", [])[j] if j < len(profile.get("certificates", [])) else None
        return [{"where": f"certificates:{j}", "old": old, "new": f"{old} · {a}"}] if old else []
    if sec == "summary":
        old = profile.get("summary", "")
        return [{"where": "summary", "old": old, "new": (old.rstrip() + " " + _sentence(a)).strip() if old else _sentence(a)}]
    if sec == "skills":
        have = {i.lower() for g in profile.get("skills", []) for i in g["items"]}
        items = [x for x in _split_list(a) if x.lower() not in have]
        return [{"where": "skills:+", "old": "", "new": ", ".join(items)}] if items else []
    if sec in ("certificates", "education"):
        return [{"where": f"{sec}:+", "old": "", "new": x} for x in _split_list(a) if len(x) > 2]
    if sec == "extras":
        return [{"where": "extras:+", "old": "", "new": x} for x in re.split(r"[;\n]", a) if len(x.strip()) > 2]
    m = re.match(r"exp:(\d+)$", sec)
    if m:
        return [{"where": f"exp:{m.group(1)}:+", "old": "", "new": _sentence(x)} for x in re.split(r"[;\n]", a) if x.strip()]
    return [{"where": "extras:+", "old": "", "new": _sentence(a).rstrip(".")}]


def is_known_typo(wrong, fix):
    """Yalnızca TYPO_HINTS'teki gerçek bir (yanlış → doğru) çifti denetimsiz uygulanabilir."""
    return bool(wrong) and any(f == fix and re.fullmatch(pat, wrong) for pat, f in cs.TYPO_HINTS.items())


def _validate(edit, src, years):
    from ai_engine.cv_builder import check_text
    if edit["where"] == "typo":
        return [] if is_known_typo(edit.get("old"), edit["new"]) else ["bilinmeyen yazım düzeltmesi"]
    why = check_text(edit["new"], src + "\n" + (edit.get("old") or ""), years)  # değiştirilen metin zaten CV'de
    if edit.get("old") and (edit["where"] in ("headline", "summary", "languages")
                            or re.match(r"(exp:\d+:\d+|certificates:\d+)$", edit["where"])):
        why += cs.info_loss(edit["old"], edit["new"])  # mevcut bilgiyi silen yeniden yazım reddedilir
    return why


def propose_edits(profile, original, qa, use_ai=True, model=None):
    """qa: [{...soru, "answer": str}]. Cevaplar CV'ye nasıl işlenir? Her öneri kaynağa karşı denetlenir.
    Dönüş: {"accepted": [...], "rejected": [...], "ai_error": str|None}"""
    answered = [q for q in qa if q["section"] == "typo" and (q.get("answer") or "").strip()
                or q["section"] != "typo" and is_real_answer(q.get("answer"))]
    src = cs.source_text(profile, original) + "\n" + "\n".join(q["answer"] for q in answered)
    years = cv_years(original)
    out = {"accepted": [], "rejected": [], "ai_error": None}
    covered, claimed = set(), {}  # claimed: hedef → o hedefe kabul edilmiş son metin

    def add(edit, key):
        edit["new"] = (edit.get("new") or "").strip()
        w = edit["where"]
        if w in claimed:  # aynı hedefe ikinci öneri: ilkinin üzerine kurulur, onu silemez
            m = re.match(r"exp:(\d+):\d+$", w)
            if m:
                edit = {**edit, "where": f"exp:{m.group(1)}:+", "old": ""}
            elif w in ("headline", "summary", "languages") or w.startswith("certificates:"):
                edit = {**edit, "old": claimed[w]}
        if not edit["new"] or edit["new"] == (edit.get("old") or ""):
            return
        edit["label"], edit["key"] = _label(profile, edit["where"]), key
        why = _validate(edit, src, years)
        m = re.match(r"exp:(\d+):\d+$", edit["where"])
        if why and m and not cs.check_text_only(edit["new"], src, years):
            # mevcut maddeyi yeniden yazarken bilgi siliyordu: metin temiz → yeni madde olarak öner
            edit = {**edit, "where": f"exp:{m.group(1)}:+", "old": ""}
            edit["label"] = _label(profile, edit["where"])
            why = []
        if why:
            out["rejected"].append({**edit, "why": why})
        else:
            out["accepted"].append(edit)
            covered.add(key)
            if not edit["where"].endswith(":+") and edit["where"] != "typo":
                claimed[edit["where"]] = edit["new"]

    direct = ("typo", "languages", "links")  # modele gerek yok: cevap olduğu gibi kullanılır
    for q in answered:
        if q["section"] in direct or q["section"].startswith("cert:"):
            for e in fallback_edits(profile, q, q["answer"]):
                add(e, q["key"])
    rest = [q for q in answered if q["section"] not in direct and not q["section"].startswith("cert:")]
    if rest and use_ai:
        try:
            out_ai = _ai_edits(profile, rest, model)
            for e in out_ai:
                k = e.pop("answer", None)
                key = rest[k]["key"] if isinstance(k, int) and 0 <= k < len(rest) else None
                where = str(e.get("where", "")).strip()
                if key is None or not _WHERE_RE.match(where) or _old_value(profile, where) is None:
                    continue
                add({"where": where, "old": _old_value(profile, where), "new": str(e.get("text", ""))}, key)
        except Exception as ex:
            out["ai_error"] = str(ex)
            log.warning("Yapay zekâ düzenleme önerisi üretemedi: %s", ex)
    for q in rest:  # yapay zekâ kullanamadıysa ya da cevabı kaçırdıysa: cevap olduğu gibi eklenir
        if q["key"] not in covered:
            for e in fallback_edits(profile, q, q["answer"]):
                add(e, q["key"])
    return out


def _ai_edits(profile, rest, model=None):
    from ai_engine.brain import _chat_json, fast_model
    system = ("Sen kıdemli bir Türk İK uzmanı ve CV editörüsün. Adayın SORULARA VERDİĞİ CEVAPLARI CV'ye profesyonel "
              "dille işleyeceksin. SADECE CV'deki ve cevaplardaki bilgileri kullan; yeni sayı, beceri, şirket, unvan "
              "UYDURMA. Mevcut bir maddeyi yeniden yazıyorsan oradaki hiçbir teknolojiyi, sayıyı ve görevi silme. "
              "Sadece istenen JSON'u döndür.")
    qa_txt = "\n".join(f"[{k}] BÖLÜM={q['section']} | SORU: {q['question']}\n    CEVAP: {q['answer']}" for k, q in enumerate(rest))
    user = f"""CV:
{cs._profile_prompt(profile)}

SORULAR VE ADAYIN CEVAPLARI:
{qa_txt}

GÖREV: Her cevabı CV'ye işle. Her düzenleme için:
- where: "headline" | "summary" | "exp:N:M" (N. deneyimin M. maddesini yeniden yaz; köşeli parantezdeki numaralar)
  | "exp:N:+" (N. deneyime yeni madde) | "skills:+" (virgülle ayrılmış YENİ beceriler) | "certificates:+" |
  "education:+" | "extras:+"
- text: CV'ye girecek metin. Madde ise tek cümle, güçlü fiille ve birinci tekil şahısla ("Yönettim", "Kurdum").
  Cevaptaki sayıları aynen koru.
- answer: hangi cevaptan geldiği (köşeli parantezdeki numara).
Cevap bir maddeyi sayıyla güçlendiriyorsa o maddeyi (exp:N:M) yeniden yaz; yeni bir görevse exp:N:+ kullan.
Boş, "yok", "bilmiyorum" gibi cevaplar için düzenleme ÜRETME."""
    data = _chat_json(system, user, "cv_answer_edits", _EDIT_SCHEMA, temperature=0.2, model=model or fast_model(),
                      timeout=AI_TIMEOUT, max_tokens=1500)
    return [dict(e) for e in data.get("edits", [])]


# ---------------------------------------------------------------- 3) uygula
def _fix_typo(p, wrong, fix):
    pat = re.compile(rf"(?<![\w]){re.escape(wrong)}(?![\w])")
    sub = lambda t: pat.sub(lambda _m: fix, t or "")  # noqa: E731 — fix şablon değil düz metin
    for k in ("headline", "summary", "languages"):
        p[k] = sub(p.get(k, ""))
    for k in ("education", "certificates", "extras"):
        p[k] = [sub(x) for x in p.get(k, [])]
    for ex in p.get("experience", []):
        ex["title"] = sub(ex.get("title"))
        for b in ex["bullets"]:
            b["text"] = sub(b["text"])
    for g in p.get("skills", []):
        g["items"] = [sub(i) for i in g["items"]]


def apply_edits(profile, edits, qa=()):
    """Onaylanan düzenlemeleri uygular; cevapları qa_log'a yazar (sonraki turlarda tekrar sorulmaz ve
    uydurma denetiminde kaynak sayılır). Öneriden bu yana hedef metin değiştiyse (elle düzenleme, yeni CV)
    o düzenleme ATLANIR — yanlış maddenin üzerine yazılmaz. Dönüş: atlanan düzenlemeler."""
    p, skipped = profile, []
    for e in edits:
        w, new = e["where"], e["new"]
        current = _old_value(p, w)
        if w == "typo":
            if is_known_typo(e.get("old"), new):
                _fix_typo(p, e["old"], new)
            else:
                skipped.append(e)
            continue
        if current is None or (current != (e.get("old") or "") and not w.endswith(":+")):
            skipped.append(e)
            continue
        if w in ("headline", "summary", "languages"):
            p[w] = new
        elif w == "skills:+":
            have = {i.lower() for g in p["skills"] for i in g["items"]}
            items = [x for x in _split_list(new) if x.lower() not in have]
            if items:
                grp = next((g for g in p["skills"] if g["group"] == "Diğer Araçlar"), None)
                if grp is None:
                    grp = {"group": "Diğer Araçlar", "items": []}
                    p["skills"].append(grp)
                grp["items"] += items
        elif re.match(r"certificates:\d+$", w):
            j = int(w.split(":")[1])
            if j < len(p.get("certificates", [])):
                p["certificates"][j] = new
        elif w in ("certificates:+", "education:+", "extras:+", "links:+"):
            key = w.split(":")[0]
            p.setdefault(key, [])
            if new not in p[key]:
                p[key].append(new)
        else:
            m = re.match(r"exp:(\d+):(\d+|\+)$", w)
            if not m:
                continue
            exp = p["experience"][int(m.group(1))]
            if m.group(2) == "+":
                exp["bullets"].append({"text": new, "user": True})
            else:
                exp["bullets"][int(m.group(2))] = {"text": new, "user": True}
    today = date.today().isoformat()
    log_ = p.setdefault("qa_log", [])
    for q in qa:
        if q.get("key") in {x.get("key") for x in log_}:
            continue
        log_.append({"key": q["key"], "question": q["question"], "answer": (q.get("answer") or "").strip(),
                     "section": q["section"], "date": today})
    return skipped
