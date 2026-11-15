"""Canlı platform testleri (LinkedIn + Kariyer.net) — SADECE OKUMA / LİSTELEME.

Başvuru veya davet GÖNDERMEZ. Hesap koruması (guard) limitlerine tabidir; limit doluysa test 'ATLANDI' olur.
Çalıştırma:  venv/bin/python scripts/canli_test.py [linkedin|kariyer|hepsi]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import account, context, guard  # noqa: E402

context.set_user(os.environ.get("KO_USER", context.DEFAULT_USER))
SONUC = []


def test(ad, fn):
    t = time.time()
    try:
        durum, ayrinti = fn()
    except Exception as e:  # test betiği: her hatayı raporla, devam et
        durum, ayrinti = "HATA", f"{type(e).__name__}: {e}"
    SONUC.append((ad, durum, ayrinti, time.time() - t))
    print(f"[{durum:7}] {ad} ({time.time() - t:.0f} sn) — {ayrinti}", flush=True)


def _oturum(plat):
    from browser.automator import session_status
    ok = session_status()[plat]
    return ("GEÇTİ" if ok else "KALDI"), ("oturum açık" if ok else "giriş yapılmamış")


def li_ilan():
    from browser.scraper import scrape_linkedin_jobs
    st = scrape_linkedin_jobs("Sistem Yöneticisi", "Ankara")
    if st["error"] and st["error"].startswith("🛡️"):
        return "ATLANDI", st["error"]
    ok = st["found"] > 0 and not st["error"]
    return ("GEÇTİ" if ok else "KALDI"), f"{st['found']} bulundu, {st['added']} yeni, {st['duplicate']} kayıtlı, {st['irrelevant']} elendi"


def li_kisi():
    from browser.automator import find_hr_people
    r = find_hr_people("İnsan Kaynakları Müdürü", "Ankara", limit=5, max_pages=1)
    if r["error"]:
        return ("ATLANDI" if r["error"].startswith("🛡️") else "KALDI"), r["error"]
    known = [p["name"] for p in r["people"] if account.is_known_person(p["url"])]
    if known:
        return "KALDI", f"bağlantı/davetli kişi listede: {known}"
    names = ", ".join(f"{p['name']} ({p['headline'][:30]})" for p in r["people"])
    return "GEÇTİ", f"{len(r['people'])} yeni kişi, hiçbiri ağında değil: {names or '-'}"


def li_senkron():
    from browser.automator import sync_linkedin_account
    r = sync_linkedin_account()
    if not r["ok"]:
        return ("ATLANDI" if (r["error"] or "").startswith("🛡️") else "KALDI"), r["error"]
    return "GEÇTİ", r["summary"]


def kn_ilan():
    from browser.automator import scrape_kariyernet_browser
    st = scrape_kariyernet_browser("Sistem Yöneticisi", "Ankara")
    if st["error"] and st["error"].startswith("🛡️"):
        return "ATLANDI", st["error"]
    ok = st["found"] > 0 and not st["error"]
    return ("GEÇTİ" if ok else "KALDI"), (st["error"] or
                                          f"{st['found']} bulundu, {st['added']} yeni, {st['duplicate']} kayıtlı, {st['irrelevant']} elendi")


def kn_senkron():
    from browser.automator import sync_kariyernet_account
    r = sync_kariyernet_account()
    if not r["ok"]:
        return ("ATLANDI" if (r["error"] or "").startswith("🛡️") else "KALDI"), r["error"]
    return "GEÇTİ", r["summary"]


if __name__ == "__main__":
    hangi = (sys.argv[1] if len(sys.argv) > 1 else "hepsi").lower()
    print(f"Kullanıcı: {context.name()} · {time.strftime('%d.%m.%Y %H:%M')}")
    if hangi in ("linkedin", "hepsi"):
        test("LinkedIn oturum", lambda: _oturum("LinkedIn"))
        test("LinkedIn ilan çekme (Sistem Yöneticisi / Ankara)", li_ilan)
        test("LinkedIn İK kişi arama (sadece liste)", li_kisi)
        test("LinkedIn hesap senkronu", li_senkron)
    if hangi in ("kariyer", "hepsi"):
        test("Kariyer.net oturum", lambda: _oturum("Kariyer.net"))
        test("Kariyer.net ilan çekme (tarayıcı)", kn_ilan)
        test("Kariyer.net başvuru senkronu", kn_senkron)
    print("\nÖZET: " + ", ".join(f"{d}: {sum(1 for s in SONUC if s[1] == d)}" for d in ("GEÇTİ", "KALDI", "HATA", "ATLANDI")))
    for plat in ("LinkedIn", "Kariyer.net"):
        g = guard.status(plat)
        print(f"{plat} koruma: " + " · ".join(f"{k} {v['bugün']}" for k, v in g.items() if k != "engel") +
              (f" · ENGEL: {g['engel']}" if g["engel"] else ""))
