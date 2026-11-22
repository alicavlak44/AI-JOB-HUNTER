"""Otomatik İlan Avcısı — panelden (Toplu Başvuru → Otomatik ilan avcısı → Başlat) ya da elle çalıştırılır:
  KO_USER=<kullanıcı> nohup caffeinate -ims venv/bin/python -u scripts/ilan_avcisi.py >> logs/ilan_avcisi_<kullanıcı>.log 2>&1 &

Her döngüde (varsayılan 2 saatte bir, 08:00–23:00 arası):
1) Hedef pozisyonları LinkedIn'den (ve açıksa Kariyer.net'ten) tarar — hesap koruması limitleriyle.
2) LM Studio açıksa bekleyen ilanları hızlı analiz eder.
3) Uyum puanı %75+ olan ilanlar için tam analiz (ön yazı + İK notu) ve isteğe bağlı ilana özel CV hazırlar.
4) Yeni hazır fırsat çıkınca macOS bildirimi gönderir.
5) Günde 1 kez LinkedIn hesabını senkronlayarak kabul/başvuru durumunu taze tutar.

Not: Kullanıcı onayı olmadan ASLA otomatik başvuru göndermez; her şeyi tek tıkla başvuruya hazır eder.
"""
import os
import signal
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KO_HEADLESS", "1")  # arka planda pencere açmadan sessiz çalışır

from app import account, campaign, context, guard, jobbot  # noqa: E402
from app.settings import STATUS_ANALYZED  # noqa: E402
from database.db_manager import get_all_jobs, init_db, set_tailored_cv  # noqa: E402
from database.stats import parse_score  # noqa: E402

SLUG = os.environ.get("KO_USER") or context.DEFAULT_USER
context.set_user(SLUG)
init_db()

USE_KARIYERNET = os.environ.get("JOBBOT_KARIYERNET", "1") == "1"
AUTO_CV = os.environ.get("JOBBOT_AUTO_CV", "1") == "1"
AUTO_SYNC = os.environ.get("JOBBOT_AUTO_SYNC", "1") == "1"
START_H, END_H = jobbot.WORK_HOURS
INTERVAL_SEC = max(15, jobbot.INTERVAL_MIN) * 60


def log(*a, state=None, **extra):
    line = " ".join(str(x) for x in a)
    print(datetime.now().strftime("%d.%m %H:%M"), line, flush=True)
    try:
        jobbot.write_state(SLUG, detail=line[:220], **({"state": state} if state else {}), **extra)
    except OSError:
        pass


def nap(seconds):
    """Gerçek saate göre bekler: Mac uyuyup uyanınca kaldığı yerden devam eder."""
    until = datetime.now() + timedelta(seconds=seconds)
    while datetime.now() < until:
        time.sleep(min(60, max(1, (until - datetime.now()).total_seconds())))


def sleep_until_working_hours():
    now = datetime.now()
    if START_H <= now.hour < END_H:
        return
    start = now.replace(hour=START_H, minute=0, second=0, microsecond=0)
    if now.hour >= END_H:
        start += timedelta(days=1)
    log(f"Mesai dışı, {start:%d.%m %H:%M} saatine kadar bekleniyor", state="mesai dışı",
        next_run=start.strftime("%d.%m %H:%M"))
    nap((start - now).total_seconds())


def _needs_daily_sync():
    snap = account.latest_snapshot("LinkedIn")
    if not snap or not snap.get("_synced_at"):
        return True
    try:
        dt = datetime.strptime(snap["_synced_at"], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - dt).total_seconds() >= 24 * 3600
    except ValueError:
        return True


def run_cycle(cycle_idx, totals):
    from ai_engine.brain import check_lm_studio
    from ai_engine.cv_builder import build_tailored_cv
    from browser.automator import scrape_kariyernet_browser, session_status, sync_linkedin_account
    from browser.scraper import scrape_linkedin_jobs

    u = context.user()
    city = (u.get("city") or "Ankara").strip()
    targets = [t.strip() for t in (u.get("targets") or []) if t.strip()]
    if not targets:
        log("Hedef pozisyon tanımlı değil; Profil ve Ayarlar'dan ekleyin", state="beklemede")
        return

    # 1) İlan tarama (LinkedIn hızlı + isteğe bağlı Kariyer.net)
    new_found = 0
    for pos in targets:
        d = guard.wait_turn("LinkedIn", guard.SCRAPE, max_wait=25)
        if not d.ok:
            log(f"LinkedIn tarama sınırında ({d.reason}); kalan pozisyonlar sonraki tura kaldı")
            break
        log(f"LinkedIn taranıyor: {pos} ({city})", state="çalışıyor")
        st = scrape_linkedin_jobs(pos, city)
        added = int(st.get("added", 0))
        new_found += added
        if st.get("error"):
            log("LinkedIn uyarısı:", st["error"])
            if "🛡️" in st["error"]:
                break

    if USE_KARIYERNET and session_status().get("Kariyer.net") and guard.check("Kariyer.net", guard.SCRAPE).ok:
        # Her döngüde en fazla 3 pozisyon (Chrome kilidini ve limitleri yormasın)
        kn_batch = [targets[(cycle_idx * 3 + j) % len(targets)] for j in range(min(3, len(targets)))]
        for pos in kn_batch:
            d = guard.wait_turn("Kariyer.net", guard.SCRAPE, max_wait=25)
            if not d.ok:
                break
            log(f"Kariyer.net taranıyor: {pos} ({city})", state="çalışıyor")
            st = scrape_kariyernet_browser(pos, city)
            new_found += int(st.get("added", 0))
            if st.get("error"):
                log("Kariyer.net uyarısı:", st["error"])
                if "🛡️" in st["error"]:
                    break

    totals["found_total"] += new_found
    log(f"Tarama tamamlandı: {new_found} yeni ilan eklendi", **totals)

    # 1.5) Detayı eksik ilanların tam metnini çek (başvuru öncesi panelde okunabilsin)
    _fetch_missing_details(limit=15)

    # 2) Hızlı yapay zekâ analizi ve %75+ fırsat hazırlığı (yalnızca LM Studio açıksa)
    _analyze_and_prepare(totals)

    # 3) Günde 1 kez LinkedIn hesap senkronu
    if AUTO_SYNC and session_status().get("LinkedIn") and _needs_daily_sync() and guard.check("LinkedIn", guard.SYNC).ok:
        log("Günlük LinkedIn hesap senkronu yapılıyor...", state="çalışıyor")
        r = sync_linkedin_account()
        log("LinkedIn senkron:", r.get("summary") or r.get("error") or "tamamlandı")


def _prioritize_large(df):
    """Büyük/kurumsal şirketleri kuyruğun başına alır; kadro sınıfı (Tekniker/Uzman/Mühendis) ve yeni mezun
    tercihine uymayan ilanları kuyruktan eler (API kotası boşa harcanmaz)."""
    if df is None or df.empty:
        return df
    from ai_engine.company_tier import TIER_LARGE, TIER_SMALL, classify_company
    from ai_engine.role_class import matches_role_prefs
    u = context.user()
    only_large = bool(u.get("only_large_companies"))
    allowed_roles = u.get("allowed_role_classes") or None
    fresh_only = bool(u.get("fresh_grad_only"))
    d = df.copy()
    if allowed_roles or fresh_only:
        keep = [matches_role_prefs(r.get("Pozisyon"), r.get("details"), allowed_roles, fresh_only)
                for _, r in d.iterrows()]
        d = d[keep]
        if d.empty:
            return d
    tiers = [classify_company(r.get("Şirket"), r.get("details"), r.get("Pozisyon"))["tier"] for _, r in d.iterrows()]
    d["_tier"] = tiers
    if only_large:
        d = d[d["_tier"] != TIER_SMALL]
    d["_rank"] = d["_tier"].map({TIER_LARGE: 2, "Orta / İncele": 1, TIER_SMALL: 0}).fillna(1)
    return d.sort_values("_rank", ascending=False).drop(columns=["_tier", "_rank"])


def _fetch_missing_details(limit=15):
    """Detay metni eksik (200 karakter altı) ilanların tam açıklamasını sessizce çeker ve kaydeder."""
    from browser.automator import fetch_job_description_browser
    from browser.scraper import fetch_job_description
    from database.db_manager import update_job_details

    jobs = get_all_jobs()
    if jobs.empty:
        return 0
    missing = _prioritize_large(jobs[jobs["details"].fillna("").str.len() < 200]).head(limit)
    fetched = 0
    for _, row in missing.iterrows():
        url = row.get("url") or ""
        if not url:
            continue
        source = row.get("Kaynak") or ""
        desc = fetch_job_description(url) if source != "Kariyer.net" else ""
        if len(desc) < 200 and source == "Kariyer.net":
            desc = fetch_job_description_browser(url)
        if desc and len(desc) >= 80:
            update_job_details(int(row["id"]), desc)
            fetched += 1
            log(f"İlan detayı çekildi ({fetched}/{len(missing)}): {row['Şirket']} — {row['Pozisyon']}", state="çalışıyor")
    if fetched:
        log(f"{fetched} ilanın tam detayı kaydedildi")
    return fetched


def _analyze_and_prepare(totals):
    """Yapay zekâ (yerel LM Studio veya bulut API) hazırsa bekleyen ilanları analiz eder ve %75+ fırsatları hazırlar."""
    from ai_engine.brain import check_ai
    from ai_engine.cv_builder import build_tailored_cv
    from app import settings as _settings

    lm_ok, lm_msg = check_ai()
    if not lm_ok:
        log(f"Yapay zekâ hazır değil ({lm_msg}); analiz bekliyor", state="lm kapalı")
        return False
    is_cloud = _settings.ai_config()["is_cloud"]
    batch_limit = max(jobbot.MAX_ANALYZE_PER_CYCLE, 30) if is_cloud else jobbot.MAX_ANALYZE_PER_CYCLE

    jobs = get_all_jobs()
    pending = _prioritize_large(campaign.unanalyzed_jobs(jobs)).head(batch_limit)
    analyzed_now = 0
    for _, row in pending.iterrows():
        log(f"CV'ye göre ATS kontrol ediliyor: {row['Şirket']} — {row['Pozisyon']}", state="çalışıyor")
        ok, msg = campaign.analyze_job(row, brief=True)
        if ok:
            analyzed_now += 1
            totals["analyzed_total"] += 1
            log(f"ATS sonucu: {row['Şirket']} — {row['Pozisyon']} → {msg}", **totals)
            if is_cloud:
                time.sleep(2.5)  # ücretsiz bulut API RPM sınırına nazik aralık
        else:
            log(f"Analiz atlandı ({row['Şirket']}): {msg}")
            if any(k in msg for k in ("LM Studio", "ulaşılamadı", "yetkisiz", "kota", "API anahtarı")):
                break
    if analyzed_now:
        log(f"{analyzed_now} ilan analiz edildi", **totals)

    from ai_engine.company_tier import TIER_LARGE, TIER_SMALL, classify_company
    only_large = bool(context.user().get("only_large_companies"))
    jobs = get_all_jobs()
    high = jobs[jobs["Durum"] == STATUS_ANALYZED].copy()
    if not high.empty:
        high["_p"] = high["ATS Uyum"].map(parse_score)
        high = high[high["_p"].notna() & (high["_p"] >= jobbot.PREP_MIN_SCORE)].sort_values("_p", ascending=False)
        high = _prioritize_large(high)
        prepared_names = []
        for _, row in high.iterrows():
            if len(prepared_names) >= jobbot.MAX_PREP_PER_CYCLE:
                break
            ct = classify_company(row.get("Şirket"), row.get("details"), row.get("Pozisyon"))
            if ct["tier"] == TIER_SMALL or (only_large and ct["tier"] != TIER_LARGE):
                continue
            job_id = int(row["id"])
            has_cl = isinstance(row.get("cover_letter"), str) and len(row["cover_letter"].strip()) > 50
            cv_path = row.get("tailored_cv_path")
            has_cv = isinstance(cv_path, str) and bool(cv_path.strip()) and os.path.exists(cv_path)
            if has_cl and (not AUTO_CV or has_cv):
                continue
            did_work = False
            if not has_cl:
                log(f"Fırsat hazırlanıyor (%{int(row['_p'])}): {row['Şirket']} — ön yazı ve İK notu", state="çalışıyor")
                ok, _ = campaign.analyze_job(row, brief=False)
                did_work = did_work or ok
            if AUTO_CV and not has_cv:
                try:
                    log(f"Özel CV üretiliyor: {row['Şirket']} — {row['Pozisyon']}", state="çalışıyor")
                    res = build_tailored_cv(job_id, row["Pozisyon"], row["Şirket"], row["details"] or "")
                    set_tailored_cv(job_id, res["path"])
                    did_work = True
                except Exception as e:
                    log(f"Özel CV üretilemedi (#{job_id}): {e}")
            if did_work:
                totals["prepared_total"] += 1
                prepared_names.append(f"{row['Şirket']} (%{int(row['_p'])})")
        if prepared_names:
            summary = ", ".join(prepared_names)
            log(f"Başvuruya hazır fırsatlar: {summary}", **totals)
            jobbot.notify_mac("Kariyer Otonomu — Yeni Fırsat Hazır",
                              f"Ön yazı ve özel CV hazır: {summary}")
    return True


def _nap_with_lm_watch(seconds, totals):
    """Sonraki taramayı beklerken yapay zekâ (Gemini API / LM Studio) hazırsa bekleyen ilanların ATS analizini bitirir."""
    from ai_engine.brain import check_ai

    until = datetime.now() + timedelta(seconds=seconds)
    last_lm_check = datetime.now()
    while datetime.now() < until:
        time.sleep(min(20, max(1, (until - datetime.now()).total_seconds())))
        if (datetime.now() - last_lm_check).total_seconds() >= 60:
            last_lm_check = datetime.now()
            if not (START_H <= datetime.now().hour < END_H):
                continue
            pending = _prioritize_large(campaign.unanalyzed_jobs(get_all_jobs()))
            if not pending.empty and check_ai()[0]:
                log(f"Yapay zekâ hazır; bekleyen {len(pending)} ilanın CV/ATS kontrolü başlıyor...", state="çalışıyor")
                _analyze_and_prepare(totals)
                nxt = until.strftime("%d.%m %H:%M")
                log(f"ATS kontrolü bitti; sonraki tarama {until:%H:%M}", state="beklemede", next_run=nxt, **totals)


def _on_term(signum, frame):
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGTERM, _on_term)
    prev = jobbot.read_state(SLUG)
    totals = {
        "found_total": int(prev.get("found_total", 0)),
        "analyzed_total": int(prev.get("analyzed_total", 0)),
        "prepared_total": int(prev.get("prepared_total", 0)),
    }
    jobbot.write_state(SLUG, pid=os.getpid(), state="çalışıyor",
                       started=datetime.now().strftime("%Y-%m-%d %H:%M"), **totals)
    log("Otomatik ilan avcısı başladı", state="çalışıyor", **totals)
    cycle = 0
    try:
        while True:
            sleep_until_working_hours()
            try:
                run_cycle(cycle, totals)
            except Exception as e:
                log(f"Döngü hatası (sonraki turda devam edilecek): {e}", state="beklemede")
            cycle += 1
            nxt = datetime.now() + timedelta(seconds=INTERVAL_SEC)
            log(f"Tur bitti; sonraki tarama {nxt:%H:%M}", state="beklemede",
                next_run=nxt.strftime("%d.%m %H:%M"), **totals)
            _nap_with_lm_watch(INTERVAL_SEC, totals)
    finally:
        jobbot.write_state(SLUG, pid=None, state="durduruldu", **totals)


if __name__ == "__main__":
    main()
