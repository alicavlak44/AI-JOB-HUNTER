import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)
DB_DIR = os.path.join(BASE_DIR, "database")
DOCS_DIR = os.path.join(BASE_DIR, "documents")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
COVER_LETTERS_DIR = os.path.join(DOCS_DIR, "cover_letters")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "kariyer_otonomu.log")
SCREENSHOTS_DIR = os.path.join(LOGS_DIR, "screenshots")
CHROME_PROFILE = os.path.join(DB_DIR, "bot_profile")
DB_PATH = os.path.join(DB_DIR, "kariyer_otonomu_v5.db")

os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(COVER_LETTERS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# CV yolu (Büyük/küçük harf duyarlılığına karşı kontrol)
CV_PATH = os.path.join(DOCS_DIR, "Cv.pdf") if os.path.exists(os.path.join(DOCS_DIR, "Cv.pdf")) else os.path.join(DOCS_DIR, "cv.pdf")

AI_PROVIDERS = {
    "local": {
        "label": "Yerel (LM Studio)",
        "url": "http://127.0.0.1:1234/v1",
        "model": "qwen/qwen3.5-9b",
        "fast_model": "",
        "reasoning": "none",
        "needs_key": False,
    },
    "gemini": {
        "label": "Google Gemini API (Bulut)",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash",
        "fast_model": "gemini-3.5-flash-lite",
        "reasoning": "none",
        "needs_key": True,
    },
    "openai": {
        "label": "OpenAI (Bulut)",
        "url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "fast_model": "gpt-4.1-mini",
        "reasoning": "",
        "needs_key": True,
    },
    "groq": {
        "label": "Groq (Bulut)",
        "url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "fast_model": "llama-3.3-70b-versatile",
        "reasoning": "",
        "needs_key": True,
    },
    "openrouter": {
        "label": "OpenRouter (Bulut)",
        "url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash",
        "fast_model": "google/gemini-2.5-flash",
        "reasoning": "",
        "needs_key": True,
    },
    "custom": {
        "label": "Özel OpenAI Uyumlu API",
        "url": "",
        "model": "",
        "fast_model": "",
        "reasoning": "",
        "needs_key": True,
    },
}

AI_PROVIDER = os.getenv("AI_PROVIDER", "local").strip().lower()
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")
LM_API_KEY = os.getenv("LM_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
LM_MODEL = os.getenv("LM_MODEL", "qwen/qwen3.5-9b")
# Etkileşimli ekranlar (CV Koçu, Mülakat Provası) için hızlı model; boşsa LM_MODEL kullanılır.
# İlan analizi gibi arka plan işleri kalite için LM_MODEL ile çalışır.
LM_FAST_MODEL = os.getenv("LM_FAST_MODEL", "")
LM_TIMEOUT = float(os.getenv("LM_TIMEOUT", "300"))
# Düşünen modeller (Qwen3.5 vb.) için: "none" düşünmeyi kapatır (çok daha hızlı). Boş bırakılırsa gönderilmez.
LM_REASONING_EFFORT = os.getenv("LM_REASONING_EFFORT", "none")


def _read_env_file(path=None):
    """Basit KEY=VALUE okuyucu (.env değişince çalışan süreçler yeniden başlatmadan görebilsin)."""
    vals = {}
    p = path or ENV_PATH
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return vals


def ai_config(env_path=None):
    """Etkin yapay zekâ ayarlarını (.env güncel değerleriyle) döner."""
    file_env = _read_env_file(env_path)

    def get(key, default=""):
        if key in file_env:
            return file_env[key]
        return os.getenv(key, default)

    provider = (get("AI_PROVIDER", AI_PROVIDER) or "local").strip().lower()
    preset = AI_PROVIDERS.get(provider, AI_PROVIDERS["local"])
    url = (get("LM_STUDIO_URL", "") or preset["url"]).strip()
    model = (get("LM_MODEL", "") or preset["model"]).strip()
    fast = (get("LM_FAST_MODEL", "") or preset["fast_model"]).strip()
    api_key = (get("LM_API_KEY", "") or get("GEMINI_API_KEY", "") or get("OPENAI_API_KEY", "")).strip()
    # Desteklemeyen bulut sağlayıcılarda (openai/groq/openrouter) 'none' gönderilmez (400 hatasını önler)
    reasoning = get("LM_REASONING_EFFORT", preset["reasoning"]).strip()
    if provider not in ("local", "gemini") and reasoning == "none":
        reasoning = ""
    return {
        "provider": provider,
        "label": preset["label"],
        "url": url,
        "model": model,
        "fast_model": fast or model,
        "api_key": api_key,
        "reasoning_effort": reasoning,
        "needs_key": bool(preset["needs_key"]),
        "is_cloud": provider != "local",
    }


def save_ai_env(provider, url="", model="", fast_model="", api_key=None, reasoning_effort=None, env_path=None):
    """Yapay zekâ sağlayıcı ayarlarını .env dosyasına (diğer satırları koruyarak) atomik yazar."""
    p = env_path or ENV_PATH
    preset = AI_PROVIDERS.get(provider, AI_PROVIDERS["local"])
    updates = {
        "AI_PROVIDER": provider,
        "LM_STUDIO_URL": (url or preset["url"]).strip(),
        "LM_MODEL": (model or preset["model"]).strip(),
        "LM_FAST_MODEL": (fast_model or "").strip(),
        "LM_REASONING_EFFORT": (preset["reasoning"] if reasoning_effort is None else reasoning_effort).strip(),
    }
    if api_key is not None:
        updates["LM_API_KEY"] = api_key.strip()

    lines = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()

    written = set()
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                written.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in written:
            out.append(f"{k}={v}")

    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")
    os.replace(tmp, p)
    for k, v in updates.items():
        os.environ[k] = v
    return ai_config(p)
CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "Aday")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# CV metninden modele gönderilecek en fazla karakter (7-9B modellerin bağlamı için güvenli sınır)
CV_MAX_CHARS = int(os.getenv("CV_MAX_CHARS", "12000"))
JOB_DESC_MAX_CHARS = int(os.getenv("JOB_DESC_MAX_CHARS", "8000"))

DEFAULT_POSITIONS = [
    "System Administrator",
    "Network Administrator",
    "Bilgi İşlem Uzmanı",
    "Ağ ve Sistem Yöneticisi",
    "IT Specialist",
    "Linux System Administrator"
]

# JobFunnel Anti-Çöp Filtresi: IT dışı alakasız ilanları anında eler
BLACKLIST_KEYWORDS = [
    "satış", "sales", "pazarlama", "marketing", "muhasebe", "finans",
    "depo", "kalite", "üretim", "plc", "scada", "otomasyon mühendisi",
    "elektrik pano", "hemşire", "hasta", "işitme", "mağaza", "kasiyer",
    "kurye", "şoför", "sekreter", "çağrı merkezi", "müşteri temsilcisi",
    "part time", "stajyer", "satın alma", "insan kaynakları uzmanı",
    # Savunma/donanım/mekanik (BT altyapı dışı) mühendislik gürültüsü
    "mekanik tasarım", "elektronik donanım tasarım", "elektronik donanım test",
    "hava savunma", "güdüm kit", "elektro-optik", "elektronik harp",
    "güç sistem bileşen", "prototip donanım", "gömülü gerçek zamanlı",
    "aviyonik", "uçuş kontrol", "rf tasarım", "deniz haberleşme",
    "ulaşım sistemleri mekanik",
]

# Anti-Ban & Hesap Güvenliği Limitleri (LinkedIn ve Kariyer.net ban koruması)
MAX_DAILY_APPLICATIONS = int(os.getenv("MAX_DAILY_APPLICATIONS", "15"))
MAX_HOURLY_APPLICATIONS = int(os.getenv("MAX_HOURLY_APPLICATIONS", "5"))
MAX_DAILY_SCRAPES = int(os.getenv("MAX_DAILY_SCRAPES", "25"))
MIN_SCRAPE_INTERVAL_SEC = float(os.getenv("MIN_SCRAPE_INTERVAL_SEC", "12"))
MIN_APPLY_INTERVAL_SEC = float(os.getenv("MIN_APPLY_INTERVAL_SEC", "35"))
AUTO_APPLY_MIN_SCORE = int(os.getenv("AUTO_APPLY_MIN_SCORE", "65"))
MAX_WEEKLY_APPLICATIONS = int(os.getenv("MAX_WEEKLY_APPLICATIONS", "60"))
MAX_HOURLY_SCRAPES = int(os.getenv("MAX_HOURLY_SCRAPES", "8"))
# LinkedIn bağlantı davetleri (ücretsiz hesapta haftalık ~100 sınır var; altında kalıyoruz)
MAX_DAILY_INVITES = int(os.getenv("MAX_DAILY_INVITES", "15"))
MAX_WEEKLY_INVITES = int(os.getenv("MAX_WEEKLY_INVITES", "80"))
MIN_INVITE_INTERVAL_SEC = float(os.getenv("MIN_INVITE_INTERVAL_SEC", "20"))
# Platform "olağandışı etkinlik / doğrulama / 999" gösterirse o platformda tüm bot işleri bu süre durur
BLOCK_COOLDOWN_HOURS = float(os.getenv("BLOCK_COOLDOWN_HOURS", "24"))
# Geçici hız sınırı (HTTP 429) için daha kısa yerel bekleme süresi (saat)
RATE_LIMIT_COOLDOWN_HOURS = float(os.getenv("RATE_LIMIT_COOLDOWN_HOURS", "2"))

# Tarayıcı otomasyonu GİZLENMEZ (Chrome "otomatik test yazılımı tarafından kontrol ediliyor" der); platform
# doğrulama isterse bot durur (guard). Bu ayarlar sadece pencere düzeni ve dil içindir.
BROWSER_ARGS = [
    "--start-maximized",
    "--no-sandbox",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--disable-dev-shm-usage",
    "--lang=tr-TR,tr",
]

# Başvuru durumları (tek kaynak — kodun her yerinde bunlar kullanılır)
STATUS_NEW = "Yeni Bulundu"
STATUS_ANALYZED = "Analiz Hazır ✅"
STATUS_ANALYSIS_FAILED = "Analiz Hatası ⚠️"
STATUS_AT_APPLY_SCREEN = "Başvuru Ekranında 🛡️"
STATUS_APPLIED_VERIFIED = "Başvuruldu (Doğrulandı) 🚀"
STATUS_APPLY_UNVERIFIED = "Başvuru Doğrulanamadı ❓"
STATUS_APPLY_FAILED = "Başvuru Hatası ❌"

# Başvurunun gerçekten gittiğini gösteren sayfa metinleri (küçük harfle aranır)
# Not: Sadece başvuru butonuna tıklandıktan SONRA sayfada yeni beliren metinler sayılır.
APPLY_CONFIRMATION_TEXTS = [
    "başvurunuz alındı", "başvurunuz gönderildi", "başvurunuz başarıyla",
    "başvurunuz iletildi", "başvuru işleminiz tamamlandı",
    "your application was sent", "application submitted", "application was sent",
]
# İlan sayfasında daha önce başvurulduğunu gösteren metinler
ALREADY_APPLIED_TEXTS = [
    "bu ilana başvurdunuz", "başvurdunuz", "applied on", "application submitted",
]
