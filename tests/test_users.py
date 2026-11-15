"""Çok kullanıcılı yapı: kullanıcılar, PIN, kişiye özel yollar ve VERİ YALITIMI."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import context, guard, account, settings


class UsersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(context, "PROFILES_DIR", os.path.join(self.tmp, "profiles")),
            mock.patch.object(context, "USERS_FILE", os.path.join(self.tmp, "profiles", "users.json")),
            mock.patch.object(settings, "DB_PATH", os.path.join(self.tmp, "ana.db")),
            mock.patch.object(settings, "CHROME_PROFILE", os.path.join(self.tmp, "bot_profile")),
            mock.patch.object(settings, "CV_PATH", os.path.join(self.tmp, "Cv.pdf")),
            mock.patch.object(guard, "DB_PATH", None),  # etkin kullanıcının veritabanı
        ]
        for p in self.patches:
            p.start()
        context.set_user(None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        context.set_user(None)
        shutil.rmtree(self.tmp, True)

    def test_default_user_keeps_legacy_paths(self):
        users = context.load_users()
        self.assertIn(context.DEFAULT_USER, users)
        self.assertEqual(context.db_path(), settings.DB_PATH)
        self.assertEqual(context.chrome_profile(), settings.CHROME_PROFILE)
        self.assertEqual(context.field(), "it")

    def test_new_user_has_own_paths_and_field_positions(self):
        slug = context.create_user("Mücahit Cavlak", field="ik")
        self.assertEqual(slug, "mucahit-cavlak")
        context.set_user(slug)
        self.assertTrue(context.db_path().endswith(os.path.join("mucahit-cavlak", "data.db")))
        self.assertTrue(context.chrome_profile().endswith(os.path.join("mucahit-cavlak", "chrome")))
        self.assertIn("İnsan Kaynakları Uzmanı", context.user()["targets"])
        self.assertEqual(context.create_user("Mücahit Cavlak"), "mucahit-cavlak-2")  # aynı ad → ayrı kullanıcı

    def test_pin(self):
        slug = context.create_user("Ayşe", pin="1234")
        self.assertTrue(context.has_pin(slug))
        self.assertTrue(context.verify_pin(slug, "1234"))
        self.assertFalse(context.verify_pin(slug, "0000"))
        with open(context.USERS_FILE, encoding="utf-8") as f:
            self.assertNotIn("1234", f.read())  # düz metin saklanmaz
        context.update_user(slug, pin=None)
        self.assertTrue(context.verify_pin(slug, ""))

    def test_data_isolation_between_users(self):
        from database.db_manager import init_db, insert_job, get_all_jobs
        context.load_users()
        b = context.create_user("Mücahit", field="ik")
        context.set_user(context.DEFAULT_USER)
        init_db()
        insert_job("LinkedIn", "Sistem Yöneticisi", "A", "Ankara", "https://x/1")
        guard.record("LinkedIn", guard.INVITE, "kişi=X; url=https://x/in/x/")
        account.save_known_people([{"url": "https://www.linkedin.com/in/ortak/", "name": "O"}], "connection")

        context.set_user(b)
        init_db()
        self.assertTrue(get_all_jobs().empty)                       # Ali'nin ilanları görünmez
        self.assertTrue(guard.check("LinkedIn", guard.INVITE).ok)   # Ali'nin davet limiti etkilemez
        self.assertFalse(account.is_known_person("https://www.linkedin.com/in/ortak/"))  # ağlar ayrı
        insert_job("LinkedIn", "İK Uzmanı", "B", "Ankara", "https://x/2")

        context.set_user(context.DEFAULT_USER)
        self.assertEqual(get_all_jobs()["Pozisyon"].tolist(), ["Sistem Yöneticisi"])


class FieldFilterTests(unittest.TestCase):
    def test_hr_jobs_not_blacklisted_for_hr_user(self):
        from browser.scraper import is_blacklisted, is_relevant
        self.assertTrue(is_blacklisted("İnsan Kaynakları Uzmanı", "it"))
        self.assertFalse(is_blacklisted("İnsan Kaynakları Uzmanı", "ik"))
        self.assertTrue(is_relevant("Kıdemli İnsan Kaynakları Uzmanı", "İnsan Kaynakları Uzmanı", "ik"))
        self.assertFalse(is_relevant("Satış Temsilcisi", "İnsan Kaynakları Uzmanı", "ik"))
        # 2026-11-15 canlı testte yanlışlıkla elenen gerçek İK ilanları
        for title in ("Personel Özlük İşleri Uzmanı", "Associate - Human Resources", "Bordro ve Yan Haklar Uzmanı",
                      "Şube İK ve İdari İşler İş Ortağı", "İşe Alım Uzmanı", "People & Culture Business Partner"):
            self.assertTrue(is_relevant(title, "İnsan Kaynakları Uzmanı", "ik"), title)
        self.assertFalse(is_relevant("Sistem Yöneticisi", "İnsan Kaynakları Uzmanı", "ik"))


class SlugTests(unittest.TestCase):
    def test_turkish_capitals(self):
        self.assertEqual(context.slugify("Deneme İK"), "deneme-ik")
        self.assertEqual(context.slugify("Mücahit IŞIK"), "mucahit-isik")


if __name__ == "__main__":
    unittest.main()
