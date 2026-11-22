"""Toplu başvuru kampanyası: liste → kullanıcı onayı → başvuru + şirketin İK'sına davet.

Hiçbir ilana kullanıcı panelde onay kutusunu işaretlemeden başvurulmaz.
Her adım app.guard limitlerinden geçer; limit dolarsa kısa beklemeler beklenir,
uzunsa ilan "Ertelendi" olarak bırakılır; platform uyarı verirse o platformda her şey durur.
"""
import random
import time

import pandas as pd

from app import guard
from app.logger import get_logger
from app.settings import AUTO_APPLY_MIN_SCORE, STATUS_ANALYZED, STATUS_ANALYSIS_FAILED, STATUS_NEW
from database.stats import parse_score

log = get_logger("campaign")

POSTPONED = "Ertelendi ⏳"


def eligible_jobs(df, min_score=AUTO_APPLY_MIN_SCORE, only_large=False, exclude_small=False):
    """Analizi bitmiş, puanı yeterli, 'Başvurma' önerilmemiş ve henüz başvurulmamış ilanlar (puana göre sıralı).
    only_large=True: yalnızca Büyük/Kurumsal şirketler; exclude_small=True: Küçük/Riskli sinyalli ilanları eler."""
    if df is None or df.empty:
        return pd.DataFrame()
    from ai_engine.company_tier import TIER_LARGE, TIER_SMALL, classify_company
    d = df[df["Durum"] == STATUS_ANALYZED].copy()
    d["puan"] = d["ATS Uyum"].map(parse_score)
    d = d[d["puan"].notna() & (d["puan"] >= min_score)]
    # Öneri alanı boş = eski sürüm analizi (eski model her şeye yüksek puan veriyordu) → güvenilmez, alınmaz
    d = d[d["recommendation"].isin(["Başvur", "Değerlendir"])]
    if d.empty:
        return d
    tiers = [classify_company(r.get("Şirket"), r.get("details"), r.get("Pozisyon")) for _, r in d.iterrows()]
    d["olcek_tier"] = [t["tier"] for t in tiers]
    d["Ölçek"] = [t["badge"] for t in tiers]
    if only_large:
        d = d[d["olcek_tier"] == TIER_LARGE]
    elif exclude_small:
        d = d[d["olcek_tier"] != TIER_SMALL]
    # Büyük/Kurumsal şirketler aynı/yakın puanda öne çıksın
    d["_large_rank"] = (d["olcek_tier"] == TIER_LARGE).astype(int)
    return d.sort_values(["_large_rank", "puan"], ascending=[False, False]).drop(columns=["_large_rank"])


def unanalyzed_jobs(df):
    if df is None or df.empty:
        return pd.DataFrame()
    return df[df["Durum"].isin([STATUS_NEW, STATUS_ANALYSIS_FAILED])]


def save_analysis(job_id, desc, r):
    """full_ai_analysis sonucunu veritabanına yazar (panel ve toplu analiz aynı yolu kullanır)."""
    from database.db_manager import update_job_analysis
    update_job_analysis(job_id, r["score"], r["golden_keywords"], desc, r["evaluation"],
                        r["cover_letter"], r["hr_message"], r["missing_skills"], r["recommendation"],
                        r.get("cover_letter_path", ""), r["matching_skills"], r["facts"])


def analyze_job(row, brief=True):
    """Tek ilanın metnini çeker ve yapay zeka analizini yapar ve KAYDEDER. Dönüş: (başarılı_mı, mesaj).
    brief=True: toplu analizde ön yazı/İK notu üretilmez (2-3 kat hızlı); tek ilan ekranında üretilir."""
    from ai_engine.brain import full_ai_analysis, AIError
    from browser.scraper import fetch_job_description
    from browser.automator import fetch_job_description_browser
    from database.db_manager import update_job_details, update_job_status

    job_id = int(row["id"])
    desc = row["details"] if isinstance(row["details"], str) else ""
    if len(desc) < 200:
        desc = fetch_job_description(row["url"])
        if len(desc) < 200 and row["Kaynak"] == "Kariyer.net":
            desc = fetch_job_description_browser(row["url"])
        if desc:
            update_job_details(job_id, desc)
        else:  # yeni metin alınamadı → kayıtlı kısa metni silme
            desc = row["details"] if isinstance(row["details"], str) else ""
    try:
        r = full_ai_analysis(job_id, row["Pozisyon"], row["Şirket"], row["Şehir"], desc, brief=brief)
        save_analysis(job_id, desc, r)
    except AIError as e:
        update_job_status(job_id, STATUS_ANALYSIS_FAILED, error=str(e))
        return False, f"Analiz başarısız: {e}"
    except Exception as e:  # tek ilanın hatası toplu işlemi durdurmasın
        log.exception("İlan #%s analizinde beklenmeyen hata", job_id)
        update_job_status(job_id, STATUS_ANALYSIS_FAILED, error=str(e)[:300])
        return False, f"Beklenmeyen hata: {e}"
    return True, f"{r['score']} — {r['recommendation']}"


def _default_apply(job_id, url, mode, cv_path):
    from browser.automator import run_application_bot
    # toplu modda soru çıkan ilanda 90 sn beklenir (kullanıcı başındaysa doldurur), sonra sıradakine geçilir
    return run_application_bot(job_id, url, mode=mode, cv_path=cv_path, wait_user_ms=90_000)


def _default_invite(company, city):
    from browser.automator import send_hr_invites
    return send_hr_invites(company, city, max_invites=1)


def _invite_summary(inv):
    if inv.get("error"):
        return inv["error"]
    if inv.get("sent"):
        return "Davet gönderildi: " + ", ".join(inv["sent"])
    return "; ".join(inv.get("skipped") or ["—"])


def run_campaign(rows, mode="tam", invite_hr=True, max_wait=120, on_progress=None,
                 apply_fn=None, invite_fn=None, sleep=time.sleep):
    """rows: kullanıcının ONAYLADIĞI ilanlar (dict listesi: id, url, Şirket, Şehir, Pozisyon, tailored_cv_path).
    Dönüş: her ilan için sonuç sözlüğü listesi."""
    from browser.automator import choose_cv, platform_of
    apply_fn = apply_fn or _default_apply
    invite_fn = invite_fn or _default_invite
    progress = on_progress or (lambda msg: None)
    results, invited_companies = [], set()

    for i, row in enumerate(rows, 1):
        platform = platform_of(row["url"])
        label = f"[{i}/{len(rows)}] {row['Şirket']} — {row['Pozisyon']}"
        res = {"id": row["id"], "Şirket": row["Şirket"], "Pozisyon": row["Pozisyon"], "Başvuru": "", "İK": ""}

        decision = guard.check(platform, guard.APPLY)
        if not decision.ok and decision.wait_seconds <= max_wait:
            wait = decision.wait_seconds + random.uniform(3, 10)
            progress(f"{label}: hesap koruması için {wait:.0f} sn bekleniyor...")
            sleep(wait)
            decision = guard.check(platform, guard.APPLY)
        if not decision.ok:
            res["Başvuru"] = f"{POSTPONED} {decision.reason}"
            results.append(res)
            progress(f"{label}: ertelendi — {decision.reason}")
            continue

        progress(f"{label}: başvuruluyor...")
        cv = row.get("tailored_cv_path")
        status, msg = apply_fn(row["id"], row["url"], mode, choose_cv(cv if isinstance(cv, str) else None))
        res["Başvuru"] = f"{status}: {msg}" if status else msg
        blocked = guard.is_blocked(platform)  # metin eşleştirmesi değil: koruma kaydına bak

        if invite_hr and not blocked:
            key = row["Şirket"].strip().lower()
            if key in invited_companies:
                res["İK"] = "Bu şirkete bu kampanyada zaten davet gönderildi"
            else:
                progress(f"{label}: şirketin İK yöneticisi aranıyor...")
                inv = invite_fn(row["Şirket"], row.get("Şehir") or "Ankara")
                invited_companies.add(key)
                res["İK"] = _invite_summary(inv)
        results.append(res)
        log.info("Kampanya %s → %s | İK: %s", label, res["Başvuru"], res["İK"])
        if i < len(rows):
            sleep(random.uniform(20, 45))  # ilanlar arası insan hızında mola
    return results
