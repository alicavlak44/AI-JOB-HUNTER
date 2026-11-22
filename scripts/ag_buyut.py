"""Çalıştırma: panelden (İK Ağı → LinkedIn ağ botu → Başlat) ya da elle, oturumdan bağımsız:
  KO_USER=<kullanıcı> nohup caffeinate -ims venv/bin/python -u scripts/ag_buyut.py >> logs/ag_botu_<kullanıcı>.log 2>&1 &

LinkedIn ağını büyütme botu — kullanıcı yokken de çalışır (hedef: 100+ yeni bağlantı).

1) Ankara'daki büyük şirketlerin İK ve BT yöneticilerine notsuz davet (şirket başına en fazla 3+3).
2) Her şirketten sonra şirketten bağımsız arama: Ankara'daki işe alımcılar ve BT çalışanları.
Haftalık/günlük sınır dolunca bekler; 08:00-23:00 arası çalışır; LinkedIn uyarısında bekleme süresi bitince devam
eder; oturum kapanırsa durur. Bekleme gerçek saate göredir: Mac uyuyup uyansa da kaldığı yerden devam eder.
"""
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.netbot_limits import LIMITS, WORK_HOURS  # noqa: E402  (app.settings'ten ÖNCE: sınırlar ortamdan okunur)

for _k, _v in LIMITS.items():
    os.environ.setdefault(_k, _v)
os.environ.setdefault("KO_HEADLESS", "1")  # arka planda pencere açmadan sessiz çalışır

from app import context, guard, netbot  # noqa: E402

SLUG = os.environ.get("KO_USER") or context.DEFAULT_USER
context.set_user(SLUG)
from browser.automator import find_hr_people, invite_people, send_hr_invites  # noqa: E402

COMPANIES = [
    # Savunma sanayii
    "Aselsan", "Roketsan", "Havelsan", "Turkish Aerospace", "STM", "MKE", "FNSS", "Meteksan", "ASFAT", "SDT",
    "Savronik", "Altınay", "Nurol Makina", "BMC", "Otokar", "TEI", "Baykar", "Milsoft", "Yaltes", "Profen",
    "AYESAŞ", "TÜBİTAK SAGE", "TÜBİTAK BİLGEM", "Lentatek", "ELSİS", "Transvaro", "Tusaş Motor", "Aselsannet",
    # Ankara holdingleri / büyük gruplar
    "Limak", "Kolin", "Nurol", "Tepe", "Bilkent", "Yüksel", "Akfen", "Bayındır", "Cengiz", "Kalyon",
    "Rönesans", "Koç", "Sabancı", "Anadolu Grubu",
    # Telekom / teknoloji / siber güvenlik
    "Türk Telekom", "Turkcell", "Vodafone", "Türksat", "TÜBİTAK", "Siemens", "Ericsson", "Netaş", "Huawei",
    "KoçSistem", "Labris", "OBSS", "Etiya", "Innova", "Kafein", "Turkcell Global Bilgi", "Microsoft", "Cisco",
    # Finans (büyük BT ekipleri)
    "Ziraat Teknoloji", "Ziraat Bankası", "Halkbank", "Vakıfbank", "Kuveyt Türk", "Vakıf Katılım",
    "Ziraat Katılım", "PTT",
]
ROLES, SEARCHES = netbot.search_plan(context.field())
CITY = (context.user().get("city") or "Ankara").strip()
DEADLINE = datetime.now() + timedelta(days=40)
START_H, END_H = WORK_HOURS


def _company_queue():
    """Başvurulan ve yüksek uyumlu ilanların şirketleri en başta + sabit şirket listesi."""
    base = COMPANIES if CITY.replace("I", "ı").replace("İ", "i").lower() == "ankara" else []
    prio = netbot.priority_companies()
    return netbot.merge_companies(prio, base or COMPANIES)


def log(*a, state=None):
    line = " ".join(str(x) for x in a)
    print(datetime.now().strftime("%d.%m %H:%M"), line, flush=True)
    try:
        netbot.write_state(SLUG, detail=line[:200], **({"state": state} if state else {}))
    except OSError:
        pass  # durum dosyası yazılamazsa bot yine çalışsın


def nap(seconds):
    """Gerçek saate göre bekler: time.sleep Mac uyurken saymayı durdurur, bu yüzden dakikada bir saate bakılır."""
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
    log(f"Mesai dışı, {start:%d.%m %H:%M} saatine kadar bekleniyor", state="mesai dışı")
    nap((start - now).total_seconds())


def wait_for_guard():
    """Davet ve tarama izni çıkana kadar bekler (LinkedIn uyarısı dahil). False = süre doldu."""
    while datetime.now() < DEADLINE:
        sleep_until_working_hours()
        for action in (guard.INVITE, guard.SCRAPE):
            d = guard.check("LinkedIn", action)
            if not d.ok:
                log("Bekleniyor:", d.reason, state="beklemede")
                nap(min(d.wait_seconds + 90, 3 * 3600))  # en fazla 3 saatte bir yeniden bak
                break
        else:
            return True
    return False


def run_one(company, role):
    r = send_hr_invites(company, CITY, max_invites=3, role=role)
    log(company, "BT" if role == "it" else "İK", json.dumps(r, ensure_ascii=False))
    return r


def run_search(i):
    """Şirketten bağımsız arama: kişi bul (en fazla 5) ve davet et. Dönüş: (gönderilenler, hata)"""
    query, role = SEARCHES[i % len(SEARCHES)]
    found = find_hr_people(query, CITY, limit=5, max_pages=1, role=role)
    if found["error"]:
        log(f"Arama '{query}':", found["error"])
        return [], found["error"]
    res = invite_people(found["people"][:5])
    sent = [r["Kişi"] for r in res if str(r.get("Sonuç", "")).startswith("Davet gönderildi")]
    log(f"Arama '{query}' ({role}): {len(found['people'])} kişi bulundu, davet: {json.dumps(sent, ensure_ascii=False)}")
    err = next((str(r["Sonuç"]) for r in res if str(r.get("Sonuç", "")).startswith(("🛡️", "LinkedIn girişi"))), "")
    return sent, err


def _on_term(signum, frame):
    raise SystemExit(0)  # panelden "Durdur": finally bloğu durumu yazsın


def main():
    signal.signal(signal.SIGTERM, _on_term)
    netbot.write_state(SLUG, pid=os.getpid(), state="çalışıyor", sent=0, started=datetime.now().strftime("%Y-%m-%d %H:%M"))
    sent_total, stop, search_i = [], False, 0
    log("Başladı", state="çalışıyor")
    try:
        while not stop and datetime.now() < DEADLINE:
            sent_this_pass = 0
            queue = _company_queue()
            for c in queue:
                for role in ROLES:
                    if not wait_for_guard():
                        stop = True
                        break
                    netbot.write_state(SLUG, state="çalışıyor")
                    r = run_one(c, role)
                    err = r["error"] or ""
                    if "girişi yapılmadı" in err:
                        log("DUR:", err, state="giriş gerekli")
                        stop = True
                        break
                    if err.startswith("🛡️") or "Tarayıcı hatası" in err:  # sınır yarışı / geçici hata: bekle, tekrar dene
                        if wait_for_guard():
                            r = run_one(c, role)
                    sent_this_pass += len(r["sent"])
                    sent_total += r["sent"]
                    netbot.write_state(SLUG, sent=len(sent_total))
                if stop:
                    break
                if wait_for_guard():  # her şirketten sonra bir şirketten bağımsız arama (daha verimli)
                    netbot.write_state(SLUG, state="çalışıyor")
                    sent, err = run_search(search_i)
                    search_i += 1
                    sent_this_pass += len(sent)
                    sent_total += sent
                    netbot.write_state(SLUG, sent=len(sent_total))
                    if "girişi" in err:
                        log("DUR:", err, state="giriş gerekli")
                        stop = True
                        break
            log(f"Liste turu bitti: bu turda {sent_this_pass}, toplam {len(sent_total)} davet")
            if not stop and sent_this_pass == 0:
                netbot.write_state(SLUG, state="beklemede")
                nap(6 * 3600)  # herkes yakın zamanda davet edilmiş: 30 gün dolanlar için sonra yeniden dene
        log("BİTTİ. Toplam gönderilen:", len(sent_total), sent_total, state="bitti")
    finally:
        st = netbot.read_state(SLUG).get("state")
        netbot.write_state(SLUG, pid=None, state=st if st in ("bitti", "giriş gerekli") else "durduruldu")


if __name__ == "__main__":
    main()
