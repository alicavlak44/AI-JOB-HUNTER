import re
import requests
from bs4 import BeautifulSoup
import urllib.parse
from app.logger import get_logger
from app.settings import BLACKLIST_KEYWORDS, JOB_DESC_MAX_CHARS
from database.db_manager import insert_job
from app import guard

log = get_logger("scraper")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

def tr_lower(s):
    """Türkçe küçük harf: 'İŞLEM' → 'işlem' ('İ'.lower() Python'da 'i̇' verir)."""
    return (s or "").replace("I", "ı").replace("İ", "i").lower()


def _field(field=None):
    if field:
        return field
    from app import context
    return context.field()


def is_blacklisted(title, field=None):
    """BT dışı ilan kara listesi SADECE Bilgi Teknolojileri kullanıcıları için (İK arayan birinin
    'İnsan Kaynakları Uzmanı' ilanı elenmesin)."""
    if _field(field) != "it":
        return False
    t_low = tr_lower(title)
    return any(bad in t_low for bad in BLACKLIST_KEYWORDS)


# Unvan kelimeleri: aramadaki "Uzmanı" yüzünden Muhasebe Uzmanı gibi ilanlar eşleşmesin
GENERIC_TITLE_WORDS = {
    "uzmanı", "uzman", "uzmanları", "sorumlusu", "sorumlu", "mühendisi", "mühendis", "yöneticisi", "yönetici",
    "müdürü", "müdür", "elemanı", "personeli", "teknikeri", "teknisyeni", "yardımcısı", "kıdemli", "senior",
    "junior", "specialist", "engineer", "manager", "expert", "ve", "and", "of", "&", "-", "/",
}
# Bu terimlerden biri unvanda geçiyorsa ilan IT ile ilgili sayılır (kelime başında aranır)
IT_TERMS = [
    "bilgi işlem", "bilgi teknoloji", "bilişim", "information technolog", "it", "bt", "network", "ağ",
    "sistem", "system", "altyapı", "infrastructure", "siber", "cyber", "bilgi güvenliği", "security",
    "devops", "cloud", "bulut", "sunucu", "server", "help ?desk", "teknik destek", "son kullanıcı",
    "destek hizmet", "it support", "yazılım", "software", "veritaban", "database", "dba", "erp", "linux",
    "windows", "sanallaştırma", "virtuali", "noc", "soc", "data center", "veri merkezi", "donanım",
    "developer", "geliştirici", "web",
]
_IT_RE = re.compile(r"(?<![\wçğıöşü])(?:" + "|".join(IT_TERMS) + r")(?:[\wçğıöşü]*)", re.IGNORECASE)
# İnsan Kaynakları alanı: unvanda bunlardan biri varsa ilan İK ile ilgili sayılır
HR_TERMS = [
    r"insan kaynak\w*", r"ik", r"human resources?", r"hr", r"hrbp", r"bordro\w*", r"özlük", r"işe alım\w*",
    r"recruit\w*", r"talent", r"yetenek yönetim\w*", r"people (?:&|and) culture", r"people partner",
    r"personel (?:ve|&) idari\w*", r"personel işleri", r"ücret (?:ve|&) yan hak\w*", r"ücretlendirme",
    r"yan haklar", r"compensation", r"payroll", r"eğitim (?:ve|&) gelişim", r"eğitim (?:uzman|koordinatör|sorumlu)\w*",
    r"organizasyonel gelişim", r"performans yönetim\w*", r"çalışan deneyimi", r"employee experience",
]
# Kelime sınırıyla: "ik" → "İklimlendirme"yi, "personel" → "Personel Servis Şoförü"nü yakalamasın
_HR_RE = re.compile(r"(?<![\wçğıöşü])(?:" + "|".join(HR_TERMS) + r")(?![\wçğıöşü])", re.IGNORECASE)
_FIELD_RE = {"it": _IT_RE, "ik": _HR_RE}


def is_relevant(title, keyword, field=None):
    """İlan unvanı aranan pozisyonla (BT kullanıcısında genel olarak BT ile) ilgili mi?
    Kariyer.net araması gevşek: 'Bilgi İşlem Uzmanı' aramasına 'Dış Ticaret Uzmanı' da dönüyor."""
    t = tr_lower(title)
    core_words = [w for w in tr_lower(keyword).split() if w not in GENERIC_TITLE_WORDS]
    core = " ".join(core_words)
    if core and core in t:
        return True
    field_re = _FIELD_RE.get(_field(field))
    if field_re is not None:
        return bool(field_re.search(t))
    # diğer alanlar: aranan unvanın anlamlı kelimelerinden biri (ör. 'insan', 'kaynakları', 'bordro') geçmeli
    return any(len(w) > 3 and re.search(rf"(?<![\wçğıöşü]){re.escape(w)}", t) for w in core_words)


def filter_title(title, keyword, stats):
    """Kara liste / alaka kontrolü; elenen ilanları istatistiğe yazar. True = ilan alınır."""
    if is_blacklisted(title) or not is_relevant(title, keyword):
        stats["irrelevant"] += 1
        log.info("Alakasız ilan elendi: %s", title)
        return False
    return True


def new_stats():
    return {"found": 0, "added": 0, "duplicate": 0, "irrelevant": 0, "error": None}


def stats_message(source, st):
    if st["error"]:
        return f"❌ {source}: {st['error']}"
    if st["found"] == 0:
        return f"⚠️ {source}: hiç ilan bulunamadı. Arama kelimesini veya şehri değiştirmeyi deneyin."
    parts = [f"{st['found']} ilan bulundu", f"**{st['added']} yeni ilan eklendi**"]
    if st["duplicate"]:
        parts.append(f"{st['duplicate']} tanesi zaten listede")
    if st["irrelevant"]:
        parts.append(f"{st['irrelevant']} alakasız ilan elendi")
    return f"{'🎯' if st['added'] else 'ℹ️'} {source}: " + ", ".join(parts) + "."

def scrape_linkedin_jobs(keyword, city):
    """JobSpy Mimarisi: Tarayıcı açmadan, Cloudflare'e takılmadan LinkedIn Guest API'den ilan çeker."""
    encoded_kw = urllib.parse.quote(keyword)
    encoded_loc = urllib.parse.quote(city)
    st = new_stats()
    errors = []

    for i, start in enumerate([0, 25]):
        decision = guard.wait_turn("LinkedIn", guard.SCRAPE)  # her sayfadan önce (min aralık + saatlik sınır)
        if not decision.ok:
            if i == 0:
                st["error"] = "🛡️ " + decision.reason
            break
        api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={encoded_kw}&location={encoded_loc}&start={start}"
        try:
            res = requests.get(api_url, headers=HEADERS, timeout=10)
            guard.record("LinkedIn", guard.SCRAPE, f"{keyword} / {city} start={start}")
            block = guard.detect_block(http_status=res.status_code)
            if block:
                guard.report_block("LinkedIn", block)
                errors.append(f"LinkedIn bot koruması devreye girdi ({block}); hesabı korumak için taramalar "
                              f"{guard.settings.BLOCK_COOLDOWN_HOURS:.0f} saat durduruldu.")
                break
            if res.status_code != 200:
                log.warning("LinkedIn guest API %s döndü (start=%s, '%s' / %s)", res.status_code, start, keyword, city)
                errors.append(f"LinkedIn {res.status_code} hatası döndü"
                              + (" (çok sık istek; birkaç dakika bekleyin)" if res.status_code == 429 else ""))
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            cards = soup.find_all("li")

            for card in cards:
                title_el = card.find("h3", class_="base-search-card__title")
                comp_el = card.find("h4", class_="base-search-card__subtitle")
                loc_el = card.find("span", class_="job-search-card__location")
                link_el = card.find("a", class_="base-card__full-link") or card.find("a")

                if title_el and link_el and link_el.get("href"):
                    title = title_el.text.strip()
                    st["found"] += 1
                    if not filter_title(title, keyword, st):
                        continue
                    company = comp_el.text.strip() if comp_el else "Kurumsal Firma"
                    location = loc_el.text.strip() if loc_el else city
                    clean_url = link_el.get("href").split("?")[0]

                    if insert_job("LinkedIn", title, company, location, clean_url):
                        st["added"] += 1
                    else:
                        st["duplicate"] += 1
        except requests.RequestException:
            log.exception("LinkedIn isteği başarısız (start=%s)", start)
            errors.append("LinkedIn'e bağlanılamadı (internet bağlantısını kontrol edin)")
            continue
        except Exception:
            log.exception("LinkedIn sonuçları işlenemedi (start=%s)", start)
            continue
    if st["found"] == 0 and errors:
        st["error"] = errors[0]
    log.info("LinkedIn: '%s' / %s → %s", keyword, city, st)
    return st

def fetch_job_description(url):
    """İlanın iç metnini tarayıcısız okur. Kariyer.net için tarayıcı gerekir (automator)."""
    platform = "LinkedIn" if "linkedin." in (url or "") else "Kariyer.net" if "kariyer.net" in (url or "") else "diğer"
    decision = guard.wait_turn(platform, guard.FETCH)
    if not decision.ok:
        log.warning("İlan metni okunmadı (hesap koruması): %s", decision.reason)
        return ""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException:
        log.exception("İlan metni alınamadı: %s", url)
        return ""
    guard.record(platform, guard.FETCH, url[:200])
    block = guard.detect_block(http_status=res.status_code)
    if block:
        guard.report_block(platform, block)
        return ""
    if res.status_code != 200:
        log.warning("İlan metni isteği %s döndü: %s", res.status_code, url)
        return ""
    soup = BeautifulSoup(res.text, "html.parser")
    desc = soup.find("div", class_="show-more-less-html__markup") or soup.find("div", class_="description__text")
    if desc:
        return desc.get_text(separator="\n").strip()[:JOB_DESC_MAX_CHARS]
    log.warning("İlan açıklama bloğu bulunamadı, sayfa metni kullanılıyor: %s", url)
    return soup.get_text(separator="\n").strip()[:JOB_DESC_MAX_CHARS]

def build_hr_search_url(company_name, city="Ankara"):
    """Şirketin İK ve İşe Alım uzmanlarını LinkedIn'de bulan doğrudan hedef URL."""
    clean_comp = company_name.split("A.Ş")[0].split("Ltd")[0].strip()
    query = f"{clean_comp} İnsan Kaynakları OR HR OR Talent Acquisition OR İşe Alım {city}"
    return f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(query)}"
