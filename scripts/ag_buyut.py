"""Çalıştırma (oturumdan bağımsız, Mac uyumadan):
  nohup caffeinate -ims venv/bin/python scripts/ag_buyut.py >> logs/ag_botu.log 2>&1 &

LinkedIn ağını büyütme botu — kullanıcı yokken de çalışır (hedef: 100+ yeni bağlantı).

1) Ankara'daki büyük şirketlerin İK ve BT yöneticilerine notsuz davet (şirket başına en fazla 3+3).
2) Her şirketten sonra şirketten bağımsız arama: Ankara'daki işe alımcılar ve BT çalışanları.
Haftalık/günlük sınır dolunca bekler; 08:00-23:00 arası çalışır; LinkedIn uyarısında bekleme süresi bitince devam
eder; oturum kapanırsa durur. Bekleme gerçek saate göredir: Mac uyuyup uyansa da kaldığı yerden devam eder.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

# Bu botun hesap koruması sınırları (.env'dekinden bağımsız; LinkedIn ücretsiz hesap ~100 davet/hafta)
for _k, _v in {"MIN_INVITE_INTERVAL_SEC": "15", "MIN_SCRAPE_INTERVAL_SEC": "8", "MAX_HOURLY_SCRAPES": "30",
               "MAX_DAILY_SCRAPES": "120", "MAX_DAILY_INVITES": "40", "MAX_WEEKLY_INVITES": "100"}.items():
    os.environ.setdefault(_k, _v)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import context, guard  # noqa: E402

context.set_user(context.DEFAULT_USER)
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
ROLES = ["hr", "it"]
# Şirketten bağımsız: Ankara'daki işe alımcılar ve BT çalışanları (aynı alandakiler daveti daha çok kabul eder)
SEARCHES = [("IT Recruiter", "hr"), ("Sistem Yöneticisi", "it"), ("İşe Alım Uzmanı", "hr"), ("Network Engineer", "it"),
            ("Siber Güvenlik", "it"), ("Bilgi İşlem", "it"), ("Talent Acquisition", "hr"), ("Sistem Uzmanı", "it"),
            ("Bilgi Güvenliği", "it"), ("DevOps", "it"), ("İnsan Kaynakları Uzmanı", "hr"), ("Ağ Yöneticisi", "it")]
DEADLINE = datetime.now() + timedelta(days=40)
START_H, END_H = 8, 23


def log(*a):
    print(datetime.now().strftime("%d.%m %H:%M"), *a, flush=True)


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
    log(f"Mesai dışı, {start:%d.%m %H:%M} saatine kadar bekleniyor")
    nap((start - now).total_seconds())


def wait_for_guard():
    """Davet ve tarama izni çıkana kadar bekler (LinkedIn uyarısı dahil). False = süre doldu."""
    while datetime.now() < DEADLINE:
        sleep_until_working_hours()
        for action in (guard.INVITE, guard.SCRAPE):
            d = guard.check("LinkedIn", action)
            if not d.ok:
                log("Bekleniyor:", d.reason)
                nap(min(d.wait_seconds + 90, 3 * 3600))  # en fazla 3 saatte bir yeniden bak
                break
        else:
            return True
    return False


def run_one(company, role):
    r = send_hr_invites(company, "Ankara", max_invites=3, role=role)
    log(company, "BT" if role == "it" else "İK", json.dumps(r, ensure_ascii=False))
    return r


def run_search(i):
    """Şirketten bağımsız arama: kişi bul (en fazla 5) ve davet et. Dönüş: (gönderilenler, hata)"""
    query, role = SEARCHES[i % len(SEARCHES)]
    found = find_hr_people(query, "Ankara", limit=5, max_pages=1, role=role)
    if found["error"]:
        log(f"Arama '{query}':", found["error"])
        return [], found["error"]
    res = invite_people(found["people"][:5])
    sent = [r["Kişi"] for r in res if str(r.get("Sonuç", "")).startswith("Davet gönderildi")]
    log(f"Arama '{query}' ({role}): {len(found['people'])} kişi bulundu, davet: {json.dumps(sent, ensure_ascii=False)}")
    err = next((str(r["Sonuç"]) for r in res if str(r.get("Sonuç", "")).startswith(("🛡️", "LinkedIn girişi"))), "")
    return sent, err


sent_total, stop, search_i = [], False, 0
log("Başladı")
while not stop and datetime.now() < DEADLINE:
    sent_this_pass = 0
    for n, c in enumerate(COMPANIES, 1):
        for role in ROLES:
            if not wait_for_guard():
                stop = True
                break
            r = run_one(c, role)
            err = r["error"] or ""
            if "girişi yapılmadı" in err:
                log("DUR:", err)
                stop = True
                break
            if err.startswith("🛡️") or "Tarayıcı hatası" in err:  # sınır yarışı / geçici hata: bekle, bir kez daha dene
                if wait_for_guard():
                    r = run_one(c, role)
            sent_this_pass += len(r["sent"])
            sent_total += r["sent"]
        if stop:
            break
        if wait_for_guard():  # her şirketten sonra bir şirketten bağımsız arama (daha verimli)
            sent, err = run_search(search_i)
            search_i += 1
            sent_this_pass += len(sent)
            sent_total += sent
            if "girişi" in err:
                log("DUR:", err)
                stop = True
                break
    log(f"Liste turu bitti: bu turda {sent_this_pass}, toplam {len(sent_total)} davet")
    if not stop and sent_this_pass == 0:
        nap(6 * 3600)  # herkes yakın zamanda davet edilmiş: 30 gün dolanlar için sonra yeniden dene
log("BİTTİ. Toplam gönderilen:", len(sent_total), sent_total)
