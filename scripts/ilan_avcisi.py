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
        added = int(st.get("eklenen", 0))
        new_found += added
        if st.get("engel"):
            log("LinkedIn uyarısı:", st["engel"])
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
            new_found += int(st.get("eklenen", 0))
            if st.get("engel"):
                log("Kariyer.net uyarısı:", st["engel"])
                break

    totals["found_total"] += new_found
    log(f"Tarama tamamlandı: {new_found} yeni ilan eklendi", **totals)

    # 2) Hızlı yapay zekâ analizi ve %75+ fırsat hazırlığı (yalnızca LM Studio açıksa)
    _analyze_and_prepare(totals)

    # 3) Günde 1 kez LinkedIn hesap senkronu
    if AUTO_SYNC and session_status().get("LinkedIn") and _needs_daily_sync() and guard.check("LinkedIn", guard.SYNC).ok:
        log("Günlük LinkedIn hesap senkronu yapılıyor...", state="çalışıyor")
        r = sync_linkedin_account()
        log("LinkedIn senkron:", r.get("summary") or r.get("error") or "tamamlandı")


def _analyze_and_prepare(totals):
    """LM Studio açıksa bekleyen ilanları analiz eder ve %75+ fırsatları hazırlar. Açık değilse False döner."""
    from ai_engine.brain import check_lm_studio
    from ai_engine.cv_builder import build_tailored_cv

    lm_ok, lm_msg = check_lm_studio()
    if not lm_ok:
        log(f"LM Studio hazır değil ({lm_msg}); analiz bekliyor", state="lm kapalı")
        return False

    jobs = get_all_jobs()
    pending = campaign.unanalyzed_jobs(jobs).head(jobbot.MAX_ANALYZE_PER_CYCLE)
    analyzed_now = 0
    for _, row in pending.iterrows():
        log(f"Analiz ediliyor: {row['Şirket']} — {row['Pozisyon']}", state="çalışıyor")
        ok, msg = campaign.analyze_job(row, brief=True)
        if ok:
            analyzed_now += 1
            totals["analyzed_total"] += 1
        else:
            log(f"Analiz atlandı ({row['Şirket']}): {msg}")
            if "LM Studio" in msg or "ulaşılamadı" in msg:
                break
    if analyzed_now:
        log(f"{analyzed_now} ilan analiz edildi", **totals)

    jobs = get_all_jobs()
    high = jobs[jobs["Durum"] == STATUS_ANALYZED].copy()
    if not high.empty:
        high["_p"] = high["ATS Uyum"].map(parse_score)
        high = high[high["_p"].notna() & (high["_p"] >= jobbot.PREP_MIN_SCORE)].sort_values("_p", ascending=False)
        prepared_names = []
        for _, row in high.iterrows():
            if len(prepared_names) >= jobbot.MAX_PREP_PER_CYCLE:
                break
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
    """Sonraki taramayı beklerken LM Studio açılırsa ve bekleyen ilan varsa hemen analiz eder."""
    from ai_engine.brain import check_lm_studio

    until = datetime.now() + timedelta(seconds=seconds)
    last_lm_check = datetime.now()
    while datetime.now() < until:
        time.sleep(min(30, max(1, (until - datetime.now()).total_seconds())))
        if (datetime.now() - last_lm_check).total_seconds() >= 90:
            last_lm_check = datetime.now()
            if not (START_H <= datetime.now().hour < END_H):
                continue
            pending = campaign.unanalyzed_jobs(get_all_jobs())
            if not pending.empty and check_lm_studio()[0]:
                log(f"LM Studio açıldı; bekleyen {len(pending)} ilandan analiz başlıyor...", state="çalışıyor")
                _analyze_and_prepare(totals)
                nxt = until.strftime("%d.%m %H:%M")
                log(f"Analiz bitti; sonraki tarama {until:%H:%M}", state="beklemede", next_run=nxt, **totals)


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
