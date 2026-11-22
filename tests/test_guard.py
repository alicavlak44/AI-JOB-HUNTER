"""Hesap koruması (anti-ban) testleri — geçici veritabanı kullanır."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app import guard, settings

NOW = datetime(2026, 11, 15, 12, 0, 0)


class GuardTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = guard.DB_PATH
        guard.DB_PATH = self.path

    def tearDown(self):
        guard.DB_PATH = self._orig
        os.remove(self.path)

    def test_fresh_account_allowed(self):
        self.assertTrue(guard.check("LinkedIn", guard.APPLY, NOW).ok)

    def test_min_interval(self):
        guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(seconds=10))
        d = guard.check("LinkedIn", guard.APPLY, NOW)
        self.assertFalse(d.ok)
        self.assertGreater(d.wait_seconds, 0)

    def test_hourly_limit(self):
        for i in range(settings.MAX_HOURLY_APPLICATIONS):
            guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(minutes=50 - i * 5))
        d = guard.check("LinkedIn", guard.APPLY, NOW)
        self.assertFalse(d.ok)
        self.assertIn("saatlik", d.reason)

    def test_daily_limit_counts_history(self):
        # geçmiş 24 saate yayılmış başvurular (saatlik sınırı aşmadan) günlük sınırı doldurur
        for i in range(settings.MAX_DAILY_APPLICATIONS):
            guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(hours=2 + i))
        d = guard.check("LinkedIn", guard.APPLY, NOW)
        self.assertFalse(d.ok)
        self.assertIn("günlük", d.reason)

    def test_old_activity_ignored(self):
        for i in range(30):
            guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(days=10, minutes=i))
        self.assertTrue(guard.check("LinkedIn", guard.APPLY, NOW).ok)

    def test_platforms_separate(self):
        for i in range(settings.MAX_HOURLY_APPLICATIONS):
            guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(minutes=50 - i * 5))
        self.assertTrue(guard.check("Kariyer.net", guard.APPLY, NOW).ok)

    def test_block_stops_everything_until_cooldown(self):
        guard.report_block("LinkedIn", "HTTP 999", now=NOW - timedelta(hours=1))
        for action in (guard.APPLY, guard.SCRAPE, guard.INVITE):
            self.assertFalse(guard.check("LinkedIn", action, NOW).ok)
        later = NOW + timedelta(hours=settings.BLOCK_COOLDOWN_HOURS)
        self.assertTrue(guard.check("LinkedIn", guard.APPLY, later).ok)
        self.assertIsNotNone(guard.status("LinkedIn", NOW)["engel"])
        self.assertIsNone(guard.status("LinkedIn", later)["engel"])

    def test_detect_block(self):
        self.assertEqual(guard.detect_block(http_status=999), "HTTP 999")
        self.assertEqual(guard.detect_block(http_status=429), "HTTP 429")
        self.assertIsNone(guard.detect_block(http_status=200))
        self.assertIsNotNone(guard.detect_block("Let's do a quick security check"))
        self.assertIsNotNone(guard.detect_block("Hesabınızda OLAĞANDIŞI ETKİNLİK tespit edildi"))
        self.assertIsNotNone(guard.detect_block("I'M NOT A ROBOT"))
        self.assertIsNone(guard.detect_block("Kolay Başvuru  System Administrator"))
        # ilan metinlerinde geçen genel kelimeler yanlış alarm vermemeli
        self.assertIsNone(guard.detect_block("Network Security Admin: perform security checks, captcha entegrasyonu, "
                                             "güvenlik doğrulaması süreçleri"))
        self.assertIsNotNone(guard.detect_block("", url="https://www.linkedin.com/checkpoint/challenge/AgF..."))
        self.assertIsNone(guard.detect_block("", url="https://www.linkedin.com/jobs/view/123/"))

    def test_human_pause_random_range(self):
        slept = []
        for _ in range(20):
            guard.human_pause(2, 5, sleep=slept.append)
        self.assertTrue(all(2 <= s <= 5 for s in slept))
        self.assertGreater(len(set(slept)), 1)

    def test_weekly_invite_limit(self):
        for i in range(settings.MAX_WEEKLY_INVITES):
            guard.record("LinkedIn", guard.INVITE, now=NOW - timedelta(days=1 + i % 6, minutes=i))
        d = guard.check("LinkedIn", guard.INVITE, NOW)
        self.assertFalse(d.ok)
        self.assertIn("haftalık", d.reason)


class PlatformTests(unittest.TestCase):
    def test_platform_of(self):
        from browser.automator import platform_of
        self.assertEqual(platform_of("https://www.linkedin.com/jobs/view/1"), "LinkedIn")
        self.assertEqual(platform_of("https://www.kariyer.net/is-ilani/x"), "Kariyer.net")



class LoginWallIsNotBlockTests(unittest.TestCase):
    def test_authwall_not_block(self):
        self.assertIsNone(guard.detect_block("", url="https://www.linkedin.com/authwall?trk=bf&original_referer="))


class ResetTimeTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig, guard.DB_PATH = guard.DB_PATH, self.path

    def tearDown(self):
        guard.DB_PATH = self._orig
        os.remove(self.path)

    def test_hourly_reset_is_when_oldest_expires(self):
        for m in (50, 40, 30, 20, 10):  # 5 başvuru: en eskisi 50 dk önce
            guard.record("LinkedIn", guard.APPLY, now=NOW - timedelta(minutes=m))
        d = guard.check("LinkedIn", guard.APPLY, NOW)
        self.assertFalse(d.ok)
        self.assertAlmostEqual(d.wait_seconds, 10 * 60, delta=1)  # 10 dk sonra açılır, 1 saat değil
        self.assertIn("10 dk sonra (12:10)", d.reason)


    def test_429_has_shorter_cooldown_and_clear_block(self):
        guard.report_block("LinkedIn", "HTTP 429", now=NOW - timedelta(hours=1))
        self.assertFalse(guard.check("LinkedIn", guard.SCRAPE, NOW).ok)
        after_short = NOW + timedelta(hours=settings.RATE_LIMIT_COOLDOWN_HOURS)
        self.assertTrue(guard.check("LinkedIn", guard.SCRAPE, after_short).ok)
        # Manuel sıfırlama (hesap doğrulandıktan sonra)
        self.assertGreaterEqual(guard.clear_block("LinkedIn"), 1)
        self.assertTrue(guard.check("LinkedIn", guard.SCRAPE, NOW).ok)


if __name__ == "__main__":
    unittest.main()
