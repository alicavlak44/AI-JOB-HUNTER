"""LinkedIn ağ botunun hesap koruması sınırları (LinkedIn ücretsiz hesap ~100 davet/hafta).

Ayrı dosyada: bot bu değerleri app.settings yüklenmeden ÖNCE ortam değişkeni olarak ayarlar.
"""
LIMITS = {"MIN_INVITE_INTERVAL_SEC": "15", "MIN_SCRAPE_INTERVAL_SEC": "8", "MAX_HOURLY_SCRAPES": "30",
          "MAX_DAILY_SCRAPES": "120", "MAX_DAILY_INVITES": "40", "MAX_WEEKLY_INVITES": "100"}
WORK_HOURS = (8, 23)
