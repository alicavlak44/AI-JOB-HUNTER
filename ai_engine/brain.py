"""Yapay zeka motoru: LM Studio (OpenAI uyumlu API) üzerinden CV ve ilan analizi.

Model cevapları JSON şemasıyla zorlanır (response_format=json_schema), böylece
etiket ayrıştırma hatası veya uydurma varsayılan puan oluşmaz.
"""
import json
import os
import re
from datetime import datetime
from functools import lru_cache

from openai import (OpenAI, APIConnectionError, APITimeoutError, APIStatusError,
                    AuthenticationError, BadRequestError, NotFoundError, RateLimitError)
from pypdf import PdfReader

from ai_engine.cv_profile import build_profile
from ai_engine.job_matcher import (match, find_skills, blended_score, recommendation_for,
                                   verify_requirements, rubric_score, FIELD_FIT_LABELS,
                                   drop_profile_requirements)

_GENERIC_FIT = {0: "tamamen farklı meslek", 1: "uzak ilgili meslek", 2: "aynı sektör, farklı rol",
                3: "yakın rol", 4: "aynı rol"}


def _field_fit_text():
    """Alan yakınlığı ölçeği: BT örnekleri sadece BT kullanıcısında (İK arayan biri için 'İK = farklı meslek' olmasın)."""
    from app import context
    labels = FIELD_FIT_LABELS if context.field() == "it" else _GENERIC_FIT
    return "\n".join(f"    {k} = {v}" for k, v in labels.items())
from app import settings as _settings
from app.logger import get_logger
from app.settings import (
    LM_STUDIO_URL, LM_MODEL, LM_FAST_MODEL, LM_TIMEOUT, LM_REASONING_EFFORT,
    CV_MAX_CHARS, JOB_DESC_MAX_CHARS,
)

log = get_logger("brain")


class AIError(RuntimeError):
    """Yapay zekâ sunucusuna/API'sine ulaşılamadığında veya geçersiz cevap döndüğünde fırlatılır."""


def _ai_cfg():
    return _settings.ai_config()


def _client():
    cfg = _ai_cfg()
    return OpenAI(base_url=cfg["url"], api_key=cfg["api_key"] or "lm-studio", timeout=LM_TIMEOUT, max_retries=1)


def fast_model():
    """Etkileşimli ekranlar için model: LM_FAST_MODEL ayarlıysa o, değilse ana model."""
    return _ai_cfg()["fast_model"]


def _model_matches(target, available):
    """Gemini 'models/gemini-2.5-flash' gibi ön ek döndürdüğünde de modeli eşleştirir."""
    t = (target or "").strip()
    return any(m == t or m == f"models/{t}" or m.endswith("/" + t) for m in available)


def check_lm_studio():
    """(çalışıyor_mu, mesaj) döner. Dashboard ve arka plan botlarındaki durum göstergesi için (yerel + bulut)."""
    cfg = _ai_cfg()
    label = cfg["label"]
    target = cfg["model"]
    if cfg["needs_key"] and not cfg["api_key"]:
        return False, f"{label} için API anahtarı eksik (Profil ve Ayarlar → Yapay Zekâ Motoru)"
    try:
        models = [m.id for m in _client().models.list().data]
    except AuthenticationError:
        return False, f"{label} API anahtarı geçersiz veya yetkisiz"
    except (APIConnectionError, APITimeoutError):
        if cfg["is_cloud"]:
            return False, f"{label} sunucusuna ulaşılamadı ({cfg['url']})"
        return False, "LM Studio sunucusu kapalı (LM Studio → Developer → Start server)"
    except Exception as e:  # beklenmedik hata: logla ama dashboard'u çökertme
        log.exception("Yapay zekâ kontrolü başarısız")
        return False, f"{label} hatası: {e}"
    if models and not _model_matches(target, models):
        preview = ", ".join(models[:8]) + ("..." if len(models) > 8 else "")
        return False, f"'{target}' bulunamadı ({label}). Mevcut: {preview}"
    return True, f"Hazır ({label}): {target}"


check_ai = check_lm_studio


def ping_ai():
    """Gerçek bir kısa JSON yanıt testi yapar; (başarılı_mı, mesaj) döner."""
    ok, msg = check_ai()
    if not ok:
        return False, msg
    try:
        res = _chat_json(
            "Sadece istenen JSON'u döndür.",
            "Hazır mısın?",
            "ping",
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
            timeout=30,
            max_tokens=256,
        )
        return True, f"{msg} · canlı JSON testi OK ({res})"
    except AIError as e:
        return False, str(e)


# ---------------------------------------------------------------- CV okuma
@lru_cache(maxsize=4)
def _read_cv_cached(path, mtime):
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    log.info("CV okundu: %s (%d karakter)", os.path.basename(path), len(text))
    return text


def read_cv_text():
    from app import context
    path = context.cv_path()
    if not os.path.exists(path):
        log.warning("CV bulunamadı: %s", path)
        return ""
    return _read_cv_cached(path, os.path.getmtime(path))


def _out(kind):
    from app import context
    return context.out_dir(kind)


def _candidate():
    from app import context
    return context.name()


def _field_label():
    from app import context
    return context.FIELDS.get(context.field(), "genel")


def _cv_for_prompt():
    cv = read_cv_text()
    if len(cv) > CV_MAX_CHARS:
        log.warning("CV %d karakter, ilk %d karakter kullanılıyor", len(cv), CV_MAX_CHARS)
    return cv[:CV_MAX_CHARS]


# ---------------------------------------------------------------- LLM çağrısı
def _chat_json(system, user, schema_name, schema, temperature=0.2, model=None, timeout=None, max_tokens=None):
    """Modelden şemaya uygun JSON ister ve dict döner. Yerel LM Studio ve bulut OpenAI-uyumlu API'lerle çalışır."""
    cfg = _ai_cfg()
    if cfg["needs_key"] and not cfg["api_key"]:
        raise AIError(f"{cfg['label']} için API anahtarı eksik (Profil ve Ayarlar → Yapay Zekâ Motoru).")
    client = _client() if timeout is None else _client().with_options(timeout=timeout, max_retries=0)
    use_model = model or cfg["model"]
    base_kwargs = dict(
        model=use_model,
        **({"reasoning_effort": cfg["reasoning_effort"]} if cfg["reasoning_effort"] else {}),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        **({"max_tokens": max_tokens} if max_tokens else {}),
    )
    strict_fmt = {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
    }
    try:
        try:
            res = client.chat.completions.create(**base_kwargs, response_format=strict_fmt)
        except BadRequestError as e:
            # Bazı bulut sağlayıcıları (ör. Groq/eski uç noktalar) strict json_schema'da 400 döner → json_object ile tekrar dene
            log.info("strict json_schema reddedildi (%s); json_object deneniyor", str(e)[:120])
            req_keys = ", ".join(schema.get("required") or list((schema.get("properties") or {}).keys()))
            fallback_msgs = [
                {"role": "system", "content": system + f"\nSadece geçerli JSON döndür. Gerekli anahtarlar: {req_keys}."},
                {"role": "user", "content": user},
            ]
            res = client.chat.completions.create(**{**base_kwargs, "messages": fallback_msgs},
                                                 response_format={"type": "json_object"})
    except AuthenticationError as e:
        raise AIError(f"{cfg['label']} API anahtarı geçersiz veya yetkisiz.") from e
    except NotFoundError as e:
        raise AIError(f"Model bulunamadı veya kullanımdan kalktı ('{use_model}'): {str(e)[:220]}") from e
    except RateLimitError as e:
        raise AIError(f"{cfg['label']} hız/kota sınırına ulaşıldı; biraz sonra tekrar deneyin.") from e
    except APITimeoutError as e:
        raise AIError("Yapay zekâ zamanında cevap vermedi; tekrar deneyin.") from e
    except APIConnectionError as e:
        hint = cfg["url"] if cfg["is_cloud"] else "LM Studio → Developer → Start server"
        raise AIError(f"{cfg['label']} sunucusuna ulaşılamadı ({hint}).") from e
    except APIStatusError as e:
        raise AIError(f"{cfg['label']} API hatası ({e.status_code}): {str(e)[:220]}") from e

    raw = res.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Bazı modeller JSON'u ``` blokları içine sarar; ilk {...} bloğunu dene
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        log.error("Model geçersiz JSON döndürdü:\n%s", raw[:2000])
        raise AIError("Model geçerli JSON üretmedi (ayrıntı logs/ klasöründe)")


# ---------------------------------------------------------------- Pozisyon çıkarma
_POSITIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "positions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 8},
    },
    "required": ["positions"],
    "additionalProperties": False,
}


def extract_positions_from_cv():
    cv = _cv_for_prompt()
    if not cv:
        raise AIError("CV bulunamadı — Profil ve Ayarlar sayfasından CV yükleyin")
    data = _chat_json(
        system=f"Sen deneyimli bir işe alım uzmanısın ({_field_label()}). Sadece istenen JSON'u döndür.",
        user=(
            f"Adayın CV'si:\n{cv}\n\n"
            "Bu adayın deneyimine en uygun 6 iş ilanı arama unvanını çıkar. "
            "Türkiye'deki iş sitelerinde (Kariyer.net, LinkedIn) gerçekten aranan, "
            "hem Türkçe hem İngilizce popüler unvanlar olsun."
        ),
        schema_name="positions",
        schema=_POSITIONS_SCHEMA,
    )
    positions = [p.strip() for p in data.get("positions", []) if len(p.strip()) > 2]
    log.info("CV'den çıkarılan pozisyonlar: %s", positions)
    return positions[:6]


# ---------------------------------------------------------------- İlan analizi
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array", "minItems": 3, "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "status": {"type": "string", "enum": ["var", "kısmen", "yok"]},
                    "evidence": {"type": "string"},
                },
                "required": ["item", "status", "evidence"],
                "additionalProperties": False,
            },
        },
        "field_fit": {"type": "integer", "minimum": 0, "maximum": 4},
        "golden_keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "missing_skills": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "evaluation": {"type": "string"},
        "cover_letter": {"type": "string"},
        "hr_message": {"type": "string"},
    },
    "required": ["requirements", "field_fit", "golden_keywords", "missing_skills", "evaluation", "cover_letter", "hr_message"],
    "additionalProperties": False,
}

# Modelin sık yaptığı "biz" ağzı hatalarını tekil şahsa çevirir
_PLURAL_FIXES = [
    (r"\bbaşvurumuzu\b", "başvurumu"), (r"\bbaşvurumuza\b", "başvuruma"), (r"\bbaşvurumuz\b", "başvurum"),
    (r"\bdeneyimlerimizle\b", "deneyimlerimle"), (r"\bdeneyimimizle\b", "deneyimimle"),
    (r"\btecrübemizle\b", "tecrübemle"), (r"\btecrübelerimizle\b", "tecrübelerimle"),
    (r"\brica ederiz\b", "rica ederim"), (r"\bdüşünüyoruz\b", "düşünüyorum"), (r"\binanıyoruz\b", "inanıyorum"),
    (r"\bgönderdik\b", "gönderdim"), (r"\bistiyoruz\b", "istiyorum"),
    (r"(\w+?)abileceğimizi\b", r"\1abileceğimi"), (r"(\w+?)ebileceğimizi\b", r"\1ebileceğimi"),
    (r"(\w+?)abileceğimize\b", r"\1abileceğime"), (r"(\w+?)ebileceğimize\b", r"\1ebileceğime"),
]


def _fix_singular(text):
    for pat, rep in _PLURAL_FIXES:
        def _sub(m, rep=rep):
            out = m.expand(rep)
            return out[:1].upper() + out[1:] if m.group(0)[:1].isupper() else out
        text = re.sub(pat, _sub, text, flags=re.IGNORECASE)
    return text


def _filter_llm_missing(items, cv_text):
    """LLM'in 'eksik' dediği ama sözlükte CV'de bulunan becerileri ayıklar (ör. CV'de olan Cisco)."""
    cv_skills = find_skills(cv_text)
    kept = []
    for item in items:
        mentioned = find_skills(item)
        if mentioned and mentioned <= cv_skills:
            log.info("LLM'in eksik saydığı '%s' CV'de mevcut; listeden çıkarıldı", item)
            continue
        kept.append(item.strip())
    return kept


def _safe_filename(text):
    text = "".join(c for c in text if c.isalnum() or c in " _-").strip()
    return re.sub(r"\s+", "_", text)[:60] or "ilan"


_BRIEF_SCHEMA = {
    **_ANALYSIS_SCHEMA,
    "properties": {k: v for k, v in _ANALYSIS_SCHEMA["properties"].items() if k not in ("cover_letter", "hr_message")},
    "required": [k for k in _ANALYSIS_SCHEMA["required"] if k not in ("cover_letter", "hr_message")],
}


def _analysis_system_prompt(cv, brief=False):
    """İlandan bağımsız (her çağrıda AYNI) talimatlar + CV. brief=True: ön yazı/İK notu istenmez."""
    tasks = f"""GÖREV (kullanıcı mesajındaki ilanı aşağıdaki CV ile karşılaştır):
- requirements: İlanın EN ÖNEMLİ 4-6 teknik şartı/görevi (deneyim yılı, bölüm, ehliyet, askerlik, seyahat HARİÇ).
  Her biri için:
    item: şartın kısa adı
    status: "var" = CV'de açıkça yazıyor; "kısmen" = benzer/ilgili deneyim var; "yok" = CV'de yok
    evidence: "var" ise CV'den KELİMESİ KELİMESİNE kısa alıntı (2-6 kelime); değilse boş "".
- field_fit: Adayın mesleğinin ilandaki role yakınlığı, tam sayı:
{_field_fit_text()}
- golden_keywords: İlanda aranan en kritik teknik anahtar kelimeler (ATS için).
- missing_skills: İlanda istenip CV'de olmayan beceri/şartlar. "CV'de AÇIKÇA bulunan" listesindekileri ASLA yazma.
- evaluation: Türkçe, 3-5 madde, her madde "- " ile başlasın. Güçlü yönler ve dikkat edilecekler.
  Deneyim süresi için DOĞRULANMIŞ GERÇEKLER'deki yıl değerini kullan."""
    if not brief:
        tasks += f"""
- cover_letter: {_candidate()} adına, şirketin İK ekibine hitaben, Türkçe, 180-250 kelimelik profesyonel ön yazı.
  Yer tutucu ([Tarih] vb.) kullanma.
- hr_message: {_candidate()}'in, ilandaki şirkette bir İK / işe alım uzmanına göndereceği LinkedIn bağlantı isteği notu.
  Adayın ağzından (birinci tekil şahıs, "ben") yazılsın, "Merhaba," diye başlasın, pozisyon adını ansın.
  Türkçe, EN FAZLA 280 karakter. Tekil konuş ("başvurumu", "başvurumuzu" değil).
- cover_letter ve hr_message içinde SADECE CV'de yazan bilgileri kullan: CV'de olmayan sertifika, ehliyet,
  deneyim veya beceri iddia etme. "BİLİNMİYOR" yazan konulardan hiç bahsetme."""
    return f"""Sen kıdemli bir işe alım ve ATS uzmanısın ({_field_label()} alanı). Dürüst ve ölçülü değerlendirirsin. Sadece istenen JSON'u döndürürsün.

{tasks}

ADAYIN CV'Sİ:
{cv}"""


def full_ai_analysis(job_id, job_title, company, city, job_desc, model=None, save=True, brief=False):
    """İlanı CV ile karşılaştırır.

    Ölçülebilir kısım (beceri eşleşmesi, deneyim yılı, bölüm şartı) kodla hesaplanır ve
    modele "doğrulanmış gerçek" olarak verilir. Model yorum, ön yazı ve İK mesajı üretir.
    Nihai puan ve öneri kodda birleştirilir. Hata durumunda AIError fırlatır.
    """
    cv = _cv_for_prompt()
    if not cv:
        raise AIError("CV bulunamadı — Profil ve Ayarlar sayfasından CV yükleyin")

    desc = (job_desc or "").strip()
    has_desc = len(desc) > 80
    if not has_desc:
        log.warning("İlan #%s için açıklama metni yok; sadece başlık üzerinden değerlendirilecek", job_id)

    profile = build_profile(read_cv_text())
    facts = match(f"{job_title}\n{desc}", read_cv_text(), profile)

    today = datetime.now().strftime("%d.%m.%Y")
    # Değişmeyen kısım (rol + görev + CV) system mesajında ve EN BAŞTA: LM Studio aynı başlangıcı
    # önbellekten okur, ilanlar arasında sadece ilan metni yeniden işlenir (prompt caching).
    system = _analysis_system_prompt(cv, brief)
    user = f"""BUGÜNÜN TARİHİ: {today}

Şirket: {company} ({city})
Pozisyon: {job_title}

İLAN METNİ:
{desc[:JOB_DESC_MAX_CHARS] if has_desc else "(İlan metni alınamadı. Sadece başlık ve şirkete göre temkinli değerlendir, puanı 60'ın üzerine çıkarma.)"}

DOĞRULANMIŞ GERÇEKLER (kodla hesaplandı, KESİN doğrudur — bunlarla ÇELİŞME):
{facts.as_prompt_text()}"""

    data = _chat_json(
        system=system,
        user=user,
        schema_name="job_analysis_brief" if brief else "job_analysis",
        schema=_BRIEF_SCHEMA if brief else _ANALYSIS_SCHEMA,
        temperature=0.3,
        model=model,
    )

    reqs, dropped = drop_profile_requirements(data.get("requirements", []))
    if dropped:
        log.info("İlan #%s: profil şartları puan dışı bırakıldı: %s", job_id, dropped)
    requirements, downgraded = verify_requirements(reqs, read_cv_text())
    if downgraded:
        log.info("İlan #%s: kanıtı CV'de bulunamayan şartlar 'kısmen'e düşürüldü: %s", job_id, downgraded)
    llm_score = rubric_score(requirements, data.get("field_fit", 0))
    score, score_notes = blended_score(llm_score, facts)
    if not has_desc and score > 60:  # ilan metni yoksa değerlendirme güvenilmez → otomatik başvuru eşiğinin altında tut
        score_notes = list(score_notes) + [f"İlan metni okunamadığı için puan {score} → 60 ile sınırlandı."]
        score = 60
    recommendation = recommendation_for(score)

    hr_msg = _fix_singular(data.get("hr_message", "").strip())
    if len(hr_msg) > 300:
        hr_msg = hr_msg[:297].rsplit(" ", 1)[0] + "..."

    missing = facts.missing_required + [
        m for m in _filter_llm_missing(data.get("missing_skills", []), cv)
        if m.lower() not in {x.lower() for x in facts.missing_required}
    ]
    if facts.missing_preferred:
        missing += [f"{m} (tercihen)" for m in facts.missing_preferred]

    evaluation = data.get("evaluation", "").strip()
    if score_notes:
        evaluation += "\n\n**Puan hesabı:** " + " ".join(score_notes)

    result = {
        "score": f"%{score}",
        "score_int": score,
        "llm_score": llm_score,
        "recommendation": recommendation,
        "golden_keywords": ", ".join(data.get("golden_keywords", [])),
        "matching_skills": ", ".join(facts.matched_required + facts.matched_preferred),
        "missing_skills": ", ".join(missing),
        "evaluation": evaluation,
        "cover_letter": _fix_singular(data.get("cover_letter", "").strip()),
        "hr_message": hr_msg,
        "facts": facts.to_dict(),
        "requirements": requirements,
        "field_fit": data.get("field_fit"),
        "score_notes": score_notes,
    }

    if not save:
        return result

    # Her ilan için ayrı dosyalar (üzerine yazma yok)
    base = f"{job_id}_{_safe_filename(company)}"
    result["cover_letter_path"] = ""
    if result["cover_letter"]:
        result["cover_letter_path"] = os.path.join(_out("cover_letters"), f"{base}_on_yazi.txt")
        with open(result["cover_letter_path"], "w", encoding="utf-8") as f:
            f.write(result["cover_letter"] + "\n")
    with open(os.path.join(_out("reports"), f"{base}_analiz.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "title": job_title, "company": company, "city": city,
                   "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                   "model": model or _ai_cfg()["model"], "had_description": has_desc,
                   "llm_raw": data, "final": {k: v for k, v in result.items() if k != "cover_letter_path"}},
                  f, ensure_ascii=False, indent=2)

    log.info("İlan #%s analiz edildi: %s %s (LLM %s, %s)", job_id, company, result["score"], llm_score, recommendation)
    return result
