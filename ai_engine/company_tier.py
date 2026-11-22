"""Şirket ölçeği ve kurumsallık sınıflandırıcısı.

Adayın kariyer hedefi büyük/kurumsal şirketlere geçiş olduğunda küçük, butik veya daralma/geçicilik
sinyali veren ilanları ayırır; büyük ölçekli (savunma, banka, telekom, holding, büyük sanayi/teknoloji)
şirketleri öne çıkarır.
"""
import re

TIER_LARGE = "Büyük / Kurumsal"
TIER_MEDIUM = "Orta / İncele"
TIER_SMALL = "Küçük / Riskli"

TIER_BADGE = {
    TIER_LARGE: "🏢 Büyük",
    TIER_MEDIUM: "🔍 İncele",
    TIER_SMALL: "⚠️ Küçük",
}


def _norm(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower().strip()


# Türkiye ve Ankara odağında bilinen büyük ölçekli / kurumsal şirketler (savunma, finans, telekom, holding, sanayi, global)
ENTERPRISE_COMPANIES = (
    # Savunma, havacılık, kamu teknolojisi
    "aselsan", "roketsan", "havelsan", "turkish aerospace", "tusaş", "tusas", "tai",
    "stm", "tei", "mke", "fnss", "meteksan", "asfat", "sdt", "baykar", "milsoft", "ayesaş",
    "savronik", "altınay", "nurol makina", "bmc", "otokar", "profen", "yaltes", "lentatek",
    "tübitak", "tubitak", "aselsannet", "karel", "ulak haberleşme", "türksat", "turksat",
    "ptt", "tcdd", "dhmi", "thk", "mia teknoloji", "mİa", "transvaro", "elsis",
    # Bankacılık, finans, sigorta, büyük fintech
    "ziraat", "halkbank", "vakıfbank", "vakifbank", "vakıf katılım", "iş bankası", "is bankasi",
    "softtech", "garanti bbva", "garanti teknoloji", "akbank", "yapı kredi", "yapi kredi",
    "qnb", "finansbank", "denizbank", "intertech", "kuveyt türk", "architecht", "teb",
    "ing bank", "hsbc", "fibabanka", "odeabank", "albaraka", "türkiye finans", "şekerbank",
    "türkiye sigorta", "anadolu sigorta", "allianz", "axa", "aksigorta", "ageSA", "agesa",
    "borsa istanbul", "takasbank", "merkezi kayıt", "bkm", "token finansal", "papara",
    "iyzico", "param", "bank of china", "merkez bankası", "tcmb", "spk", "bddk", "epdk",
    # Telekom & büyük teknoloji / global
    "türk telekom", "turk telekom", "turkcell", "vodafone", "superonline", "innova", "i̇nnova",
    "obss", "koçsistem", "kocsistem", "netaş", "netas", "etiya", "siemens", "ericsson",
    "huawei", "cisco", "microsoft", "oracle", "sap", "ibm", "hpe", "hewlett", "dell",
    "amazon", "aws", "google", "schneider electric", "bosch", "honeywell", "thales",
    "airbus", "vestel", "arçelik", "arcelik", "beko", "logo yazılım", "hitit", "kafein",
    "argela", "labris", "bilgeadam", "mplus", "concentrix", "teleperformance", "accenture",
    "deloitte", "pwc", "ey ", "kpmg", "capgemini", "ntt data", "atos", "dxc", "kyndryl",
    "straumann", "abb", "ge ", "general electric", "philips", "samsung", "lg electronics",
    # Holdingler, enerji, sanayi, ulaşım, büyük perakende & sağlık
    "koç holding", "sabancı", "sabanci", "anadolu grubu", "eczacıbaşı", "zorlu", "limak",
    "kolin", "nurol", "cengiz", "kalyon", "rönesans", "ronesans", "tepe ", "bilkent",
    "akfen", "yüksel", "alarko", "doğuş", "dogus", "enka", "tekfen", "oyak", "yıldız holding",
    "yaşar holding", "borusan", "kibar holding", "sanko", "kale grubu", "bsh ",
    "türk hava yolları", "turkish airlines", "thy", "pegasus", "sunexpress",
    "enerjisa", "başkent doğalgaz", "baskent dogalgaz", "botaş", "botas", "tpao", "eüaş",
    "teiaş", "tüpraş", "tupras", "socar", "petkim", "aygaz", "opet", "petrol ofisi", "shell",
    "şişecam", "sisecam", "ford otosan", "tofaş", "tofas", "renault", "mercedes-benz",
    "man türkiye", "hidromek", "türktraktör", "turktraktor", "erkunt", "erdemir", "isdemir",
    "kardemir", "brisa", "kordsa", "aksa", "çimsa", "akçansa", "vicat", "mİtaş", "mitaş",
    "şara enerji", "acıbadem", "acibadem", "memorial", "medicana", "mlp care", "medical park",
    "migros", "bim ", "a101", "şok market", "carrefoursa", "metro türkiye", "beymen",
    "lc waikiki", "defacto", "mavi", "trendyol", "hepsiburada", "getir", "yemeksepeti",
    "eti gıda", "ülker", "coca-cola", "unilever", "procter", "nestle", "nestlé",
    "philip morris", "jti", "pfizer", "roche", "novartis", "abdi ibrahim", "astrazeneca",
    "tanoto",
)

_ENTERPRISE_RE = re.compile(
    r"(?<![\wçğıöşü])(?:" + "|".join(re.escape(_norm(c)) for c in ENTERPRISE_COMPANIES if c.strip()) + r")",
    re.IGNORECASE,
)

# Büyük ölçek göstergeleri (ilan metninde geçerse)
_LARGE_SCALE_RE = re.compile(
    r"\b(?:[5-9]\d{2}|[1-9]\d{3,}|[1-9]\.\d{3})\s*\+?\s*"
    r"(?:çalışan|personel|employee|kullanıcı|user|kişilik|şube|mağaza|sunucu|vm|ülke)",
    re.IGNORECASE,
)
_ENTERPRISE_MARKERS = (
    "holding", "grup şirketi", "grup şirketleri", "savunma sanayi", "ar-ge merkezi",
    "genel müdürlük", "global", "uluslararası", "fortune", "iso 27001", "iso/iec 27001",
    "veri merkezi", "data center", "kurumsal altyapı", "büyük ölçekli", "kampüs",
    "bankacılık", "telekomünikasyon", "havacılık", "halka açık", "bist", "enterprise",
    "çok uluslu", "multinational", "milyar", "lider kuruluş", "öncü kuruluş",
)

# Küçük, butik veya daralma/geçicilik riski taşıyan sinyaller
_SMALL_SIGNALS = (
    "startup", "start-up", "erken aşama", "early stage", "butik", "küçük ekip", "küçük bir ekip",
    "aile şirketi", "şahıs şirketi", "kobi", "küçülme", "yeniden yapılanma", "dönemsel",
    "geçici pozisyon", "3 aylık proje", "6 aylık proje", "freelance", "ajans",
    "hem teknik destek hem", "tek kişilik", "tüm it işlerine tek başına", "part time",
    "part-time", "yarı zamanlı", "stajyer", "intern",
)

_HIDDEN_RE = re.compile(r"\b(gizli|confidential|anonymous|belirtilmemiş)\b", re.IGNORECASE)


def classify_company(company, details="", title=""):
    """Şirketi ölçek/kurumsallık açısından sınıflandırır.

    Dönüş: {"tier": TIER_LARGE|TIER_MEDIUM|TIER_SMALL, "badge": str, "reason": str, "is_large": bool}
    """
    comp_raw = (company or "").strip()
    comp = _norm(comp_raw)
    text = _norm(f"{comp_raw}\n{title or ''}\n{details or ''}")

    # 1) Bilinen büyük kurumsal şirket
    if comp and _ENTERPRISE_RE.search(comp):
        return {"tier": TIER_LARGE, "badge": TIER_BADGE[TIER_LARGE],
                "reason": "Bilinen büyük/kurumsal şirket", "is_large": True}

    # 2) Açık küçük / butik / geçici / riskli sinyaller
    small_hits = [s for s in _SMALL_SIGNALS if s in text]
    if small_hits:
        return {"tier": TIER_SMALL, "badge": TIER_BADGE[TIER_SMALL],
                "reason": f"Küçük/geçici/riskli sinyal: {', '.join(small_hits[:2])}", "is_large": False}

    # 3) İlan metninde güçlü kurumsal ölçek kanıtı
    scale_hit = bool(_LARGE_SCALE_RE.search(text))
    marker_hits = [m for m in _ENTERPRISE_MARKERS if m in text]
    is_hidden = bool(_HIDDEN_RE.search(comp))

    if scale_hit or len(marker_hits) >= 2:
        why = "Büyük ölçekli sayı/altyapı" if scale_hit else f"Kurumsal göstergeler ({', '.join(marker_hits[:2])})"
        if is_hidden:
            why = f"Şirket adı gizli ama {why.lower()}"
        return {"tier": TIER_LARGE, "badge": TIER_BADGE[TIER_LARGE], "reason": why, "is_large": True}

    if is_hidden:
        return {"tier": TIER_MEDIUM, "badge": TIER_BADGE[TIER_MEDIUM],
                "reason": "Şirket adı gizli — başvuru öncesi ölçeği teyit edin", "is_large": False}

    if "a.ş" in comp or "a.s." in comp or "anonim şirket" in comp or "inc" in comp or "gmbh" in comp or len(marker_hits) == 1:
        return {"tier": TIER_MEDIUM, "badge": TIER_BADGE[TIER_MEDIUM],
                "reason": "A.Ş./kurumsal yapı görünüyor — çalışan sayısını (200+) kontrol edin", "is_large": False}

    return {"tier": TIER_MEDIUM, "badge": TIER_BADGE[TIER_MEDIUM],
            "reason": "Ölçek doğrulanmadı — LinkedIn'den çalışan sayısını kontrol edin", "is_large": False}
