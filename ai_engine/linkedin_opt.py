"""LinkedIn Profil Optimizasyon Stüdyosu — CV'deki gerçek bilgilerden uydurmasız Başlık, Hakkında ve Yetenekler üretir.

Her yapay zekâ önerisi `cv_builder.check_text` ile doğrulanmış CV metnine karşı denetlenir; CV'de olmayan
beceri, sayı veya iddia içeren metin otomatik olarak reddedilir ve kural tabanlı güvenli metne düşer.
"""
import re

from ai_engine.cv_builder import check_text
from app.logger import get_logger

log = get_logger("linkedin_opt")

MAX_HEADLINE = 220
AI_TIMEOUT = 150

_SCHEMA = {
    "type": "object",
    "properties": {
        "headlines": {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "string"}},
        "about_tr": {"type": "string"},
        "about_en": {"type": "string"},
    },
    "required": ["headlines", "about_tr", "about_en"],
    "additionalProperties": False,
}


def _flat_skills(profile, limit=18):
    seen, out = set(), []
    for grp in profile.get("skills") or []:
        for item in grp.get("items") or []:
            s = (item or "").strip()
            k = s.lower()
            if s and k not in seen:
                seen.add(k)
                out.append(s)
                if len(out) >= limit:
                    return out
    return out


def rule_pack(profile, field="it"):
    """Model kapalıyken ya da denetim reddederse: doğrudan CV profilinden güvenli LinkedIn metinleri."""
    headline = (profile.get("headline") or "").strip()
    skills = _flat_skills(profile, 18)
    top4 = " | ".join(skills[:4])
    top6 = " · ".join(skills[:6])
    exp = profile.get("experience") or []
    latest_role = (exp[0].get("title") or "").strip() if exp else ""
    base_title = headline or latest_role or ("Sistem ve Ağ Yöneticisi" if field == "it" else "İnsan Kaynakları Uzmanı")

    headlines = []
    if top4:
        headlines.append(f"{base_title} | {top4}"[:MAX_HEADLINE])
    if top6 and top6 != top4:
        headlines.append(f"{base_title} — {top6}"[:MAX_HEADLINE])
    if latest_role and latest_role.lower() != base_title.lower():
        headlines.append(f"{base_title} · {latest_role}"[:MAX_HEADLINE])
    if not headlines:
        headlines.append(base_title[:MAX_HEADLINE])

    parts = []
    summary = (profile.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    bullets = []
    for e in exp[:2]:
        for b in (e.get("bullets") or [])[:2]:
            t = (b.get("text") if isinstance(b, dict) else str(b)).strip()
            if t:
                bullets.append(f"• {t}")
    if bullets:
        parts.append("Öne çıkan çalışmalarım:\n" + "\n".join(bullets[:4]))
    if skills:
        parts.append("Odaklandığım alanlar ve araçlar: " + ", ".join(skills[:12]) + ".")
    about_tr = "\n\n".join(parts) if parts else f"{base_title} alanında çalışıyorum."

    return {
        "headlines": headlines[:3],
        "about_tr": about_tr,
        "about_en": "",
        "skills": skills[:15],
        "source": "kural",
        "rejected": [],
    }


def generate_linkedin_pack(profile, cv_text="", field="it", use_ai=True, model=None):
    """CV profilinden LinkedIn Başlık, Hakkında (TR/EN) ve Yetenekler üretir.

    Dönüş: {"headlines": [...], "about_tr": str, "about_en": str, "skills": [...],
            "source": "yapay zekâ"|"kural", "rejected": [...], "ai_error": str?}
    """
    base = rule_pack(profile, field=field)
    source_cv = (cv_text or "").strip()
    if not use_ai or not source_cv:
        return base

    from ai_engine.cv_studio import _profile_prompt
    try:
        from ai_engine.brain import _chat_json, fast_model
        system = (
            "Sen Türkiye'de işe alım ve LinkedIn SEO uzmanısın. Adayın CV'sindeki GERÇEK bilgilerle yüksek görünürlüklü "
            "LinkedIn profil metinleri yaz. Adayda olmayan hiçbir beceri, araç, sayı, sertifika veya unvan UYDURMA. "
            "Birinci tekil şahıs ('ben') kullan. Sadece istenen JSON'u döndür."
        )
        user = f"""ADAYIN CV PROFİLİ:
{_profile_prompt(profile)}

GÖREV:
- headlines: 3 farklı LinkedIn Başlığı (her biri EN FAZLA 200 karakter). Arama sonuçlarında çıkması için CV'deki
  gerçek unvan ve en güçlü 3-5 teknik anahtar kelimeyi içersin.
- about_tr: 120-200 kelimelik Türkçe "Hakkında" metni (birinci tekil şahıs, 2-3 kısa paragraf + 3 madde).
  SADECE CV'de geçen bilgileri ve sayıları kullan.
- about_en: Aynı bilgilerin 100-170 kelimelik profesyonel İngilizce "About" özeti (sadece CV'deki gerçek bilgilerle)."""
        data = _chat_json(system, user, "linkedin_opt", _SCHEMA, temperature=0.35,
                          model=model or fast_model(), timeout=AI_TIMEOUT, max_tokens=1400)
    except Exception as e:
        log.warning("LinkedIn profil metinleri üretilemedi, kural tabanlı kullanılıyor: %s", e)
        return {**base, "ai_error": str(e)}

    rejected = []
    good_headlines = []
    for h in data.get("headlines") or []:
        h = re.sub(r"\s+", " ", (h or "")).strip()[:MAX_HEADLINE]
        if not h:
            continue
        probs = check_text(h, source_cv)
        if probs:
            rejected.append(f"Başlık reddedildi ({'; '.join(probs)}): {h[:80]}")
        else:
            good_headlines.append(h)

    about_tr = (data.get("about_tr") or "").strip()
    if about_tr:
        probs = check_text(about_tr, source_cv)
        if probs:
            rejected.append(f"Türkçe Hakkında reddedildi ({'; '.join(probs)})")
            about_tr = ""

    about_en = (data.get("about_en") or "").strip()
    if about_en:
        probs = check_text(about_en, source_cv)
        if probs:
            rejected.append(f"İngilizce About reddedildi ({'; '.join(probs)})")
            about_en = ""

    any_ai = bool(good_headlines or about_tr or about_en)
    return {
        "headlines": good_headlines or base["headlines"],
        "about_tr": about_tr or base["about_tr"],
        "about_en": about_en,
        "skills": base["skills"],
        "source": "yapay zekâ" if any_ai else "kural",
        "rejected": rejected,
    }
