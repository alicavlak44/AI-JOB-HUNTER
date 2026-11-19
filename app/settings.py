import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
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

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")
LM_MODEL = os.getenv("LM_MODEL", "qwen/qwen3.5-9b")
# Etkileşimli ekranlar (CV Koçu, Mülakat Provası) için hızlı model; boşsa LM_MODEL kullanılır.
# İlan analizi gibi arka plan işleri kalite için LM_MODEL ile çalışır.
LM_FAST_MODEL = os.getenv("LM_FAST_MODEL", "")
LM_TIMEOUT = float(os.getenv("LM_TIMEOUT", "300"))
# Düşünen modeller (Qwen3.5 vb.) için: "none" düşünmeyi kapatır (çok daha hızlı). Boş bırakılırsa gönderilmez.
LM_REASONING_EFFORT = os.getenv("LM_REASONING_EFFORT", "none")
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
    "part time", "stajyer", "satın alma", "insan kaynakları uzmanı"
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
# Platform "olağandışı etkinlik / doğrulama / 429" gösterirse o platformda tüm bot işleri bu süre durur
BLOCK_COOLDOWN_HOURS = float(os.getenv("BLOCK_COOLDOWN_HOURS", "24"))

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
