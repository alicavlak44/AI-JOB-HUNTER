# ⚡ Kariyer Otonomu

Yerel yapay zekâ ile çalışan iş arama asistanı: ilan bulur, CV'nize göre puanlar, isabetli başvuru yapar, İK ağınızı büyütür ve CV'nizi güzelleştirir. Verileriniz bilgisayarınızdan çıkmaz.

## Özellikler

| Sayfa | Ne yapar |
|---|---|
| 🏠 **Özet** | Hesap bağlantıları, bugünkü durum, başarı oranı, en önemli 3 öneri |
| 🔎 **İlanlar** | LinkedIn ve Kariyer.net'ten ilan çeker, alakasızları eler, tek ilan için analiz, başvuru ve ilana özel CV |
| 🚀 **Toplu Başvuru** | Bekleyen ilanları analiz eder, uyumu %65+ olanlardan seçtiklerinize başvurur; **Otomatik İlan Avcısı** arka planda tarayıp %75+ fırsatları ön yazı ve özel CV ile hazırlar |
| 🤝 **İK Ağı** | Şehirdeki İK yöneticilerini bulur, notsuz davet gönderir; arka plan **LinkedIn Ağ Botu** önce başvurduğunuz/yüksek uyumlu şirketlere, ardından büyük şirketlere ve genel İK/işe alım yöneticilerine davet atar |
| 📈 **Başarı** | Hesaplarınızdan (sadece okuyarak) başvuru → görüntülenme → mülakat oranları ve öneriler |
| 📄 **CV Stüdyosu** | CV içe aktar, 7 formattan birini seç, soru soran CV Koçu ile güçlendir (uydurmasız), canlı önizle, PDF/Word üret |
| 🎤 **Mülakat Provası** | Alana, CV'ye ve seçtiğiniz ilana özel sesli/yazılı yapay zekâ mülakatı (macOS Türkçe TTS + yerel `mlx-whisper`), puanlı karne ve geçmiş oturum inceleme |
| ⚙️ **Ayarlar** | Yapay zekâ & ses durumu, profil, soru hafızası, hesap koruması limitleri, loglar |

## Güvenlik ilkeleri

- **Uydurma yok:** Yapay zekânın önerdiği her cümle CV ile karşılaştırılır. CV'de olmayan beceri, sayı veya iddia içeren öneri otomatik reddedilir.
- **Hesap koruması:** Başvuru, davet ve tarama işlemleri saatlik, günlük ve haftalık limitlerle çalışır (`app/guard.py`). Platform uyarı verirse ilgili platformdaki tüm işlemler 24 saat durur. CAPTCHA çözülmez, bot gizlenmez.
- **Onay:** Başvuru ve davetler yalnızca sizin işaretlediğiniz öğelere gider.

## Başka Bir Bilgisayarda Çalıştırma (GitHub'dan Kurulum)

Ön gereksinimler: **Git**, **Python 3.11+** ve (önerilen) **Google Chrome**. Ayrıntılı düz metin notu için [KURULUM_NOTU.txt](KURULUM_NOTU.txt) dosyasına bakabilirsiniz.

### 1. Depoyu GitHub'dan indirin
```bash
git clone https://github.com/alicavlak44/AI-JOB-HUNTER.git
cd AI-JOB-HUNTER
```
*(Git kurulu değilse GitHub sayfasından **Code → Download ZIP** ile indirip klasöre çıkarabilirsiniz; ancak ileride `git pull` ile kolayca güncellemek için `git clone` önerilir.)*

### 2. Sanal ortamı kurun ve paketleri yükleyin

**macOS (Terminal):**
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\playwright install chromium
copy .env.example .env
```
*(Not: `mlx-whisper` yalnızca Apple Silicon Mac'lerde otomatik kurulur; Windows/Intel Mac'lerde atlanır ve Mülakat Provası yazılı modda sorunsuz çalışır.)*

### 3. Yapay zekâ motorunu ayarlayın (`.env`)
İki seçenekten birini seçebilirsiniz:
- **Bulut API (her bilgisayarda hızlı çalışır — önerilen):** `.env` içinde `AI_PROVIDER=gemini` (veya `openai`, `groq`, `openrouter`) ve `LM_API_KEY=...` girin (uygulama açıldıktan sonra **Profil ve Ayarlar** sayfasından da ayarlanabilir).
- **Yerel model (LM Studio):** [LM Studio](https://lmstudio.ai)'yu kurun, `qwen/qwen3.5-9b` modelini indirin ve **Developer → Start server** deyin (`AI_PROVIDER=local`).

### 4. Uygulamayı başlatın

**macOS:**
```bash
venv/bin/streamlit run app/dashboard.py
```

**Windows (PowerShell):**
```powershell
.\venv\Scripts\streamlit run app/dashboard.py
```

### 5. İlk kurulum ve güncellemeler
- İlk açılışta kullanıcı oluşturup CV'nizi yükleyin (veya `documents/Cv.pdf` olarak koyun).
- 🏠 **Özet** sayfasından LinkedIn ve Kariyer.net'e bir kez giriş yapın. Oturum bilgisayardaki yerel tarayıcı profilinde saklanır.
- Arka plan botlarını panelden tek tıkla başlatıp durdurabilirsiniz (**İK Ağı → LinkedIn ağ botu**, **Toplu Başvuru → Otomatik ilan avcısı**).
- GitHub'daki yeni güncellemeleri almak için proje klasöründe `git pull origin main` çalıştırın.

## Testler

```bash
venv/bin/python -m unittest discover -s tests
```

## Kişisel veriler

`documents/`, `profiles/`, `database/*.db`, tarayıcı profili, `.env` ve loglar **git'e girmez** (`.gitignore`). Başka bir bilgisayara geçerken bu dosyalar güvenlik gereği taşınmaz; yeni bilgisayarda `.env` ve CV'yi ekleyip bir kez giriş yapmanız yeterlidir.

## Telif Hakkı

© 2026 **Ali Cavlak** tarafından yapılmıştır. Tüm telif hakları **Ali Cavlak**'a aittir. Ayrıntılar için [LICENSE](LICENSE) dosyasına bakın.
