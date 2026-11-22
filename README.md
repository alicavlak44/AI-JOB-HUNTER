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

## Kurulum (macOS, Apple Silicon önerilir)

1. Kurulum komutları:
   ```bash
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/playwright install chromium
   cp .env.example .env
   ```
2. `.env` içinde adınızı ve modeli ayarlayın.
3. [LM Studio](https://lmstudio.ai)'yu kurun, `qwen/qwen3.5-9b` (MLX 4-bit) modelini indirin ve sunucuyu başlatın: Developer → Start server.
4. CV'nizi `documents/Cv.pdf` olarak koyun.
5. Tarayıcı işlemleri bilgisayardaki Google Chrome ile yapılır (giriş oturumu kalıcı profilde saklanır). Chrome yoksa
   Playwright'ın Chromium'u kullanılır (1. adımdaki `playwright install chromium`).
6. Arka plan botlarını panelden tek tıkla başlatıp durdurabilirsiniz (**İK Ağı → LinkedIn ağ botu**, **Toplu Başvuru → Otomatik ilan avcısı**); ikisi de `caffeinate` ile panel kapansa da çalışır ve Chrome profilini sırayla paylaşır.
7. Uygulamayı başlatın:
   ```bash
   venv/bin/streamlit run app/dashboard.py
   ```
8. 🏠 Özet sayfasından LinkedIn ve Kariyer.net'e bir kez giriş yapın. Oturum botun kendi tarayıcı profilinde saklanır.

## Testler

```bash
venv/bin/python -m unittest discover -s tests
```

## Kişisel veriler

`documents/`, `profiles/`, `database/*.db`, tarayıcı profili, `.env` ve loglar **git'e girmez** (`.gitignore`).
