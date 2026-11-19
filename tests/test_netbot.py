"""LinkedIn ağ botu yönetimi (app/netbot.py): durum dosyası, durum özeti, davet kayıtları. Süreç başlatmaz."""
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from app import netbot


class NetbotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(netbot, "LOGS_DIR", self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_state_roundtrip(self):
        self.assertEqual(netbot.read_state("u"), {})
        netbot.write_state("u", state="çalışıyor", pid=123)
        netbot.write_state("u", sent=4)
        st = netbot.read_state("u")
        self.assertEqual((st["state"], st["pid"], st["sent"]), ("çalışıyor", 123, 4))
        self.assertIn("updated", st)

    def test_pid_alive(self):
        self.assertTrue(netbot.pid_alive(os.getpid()))
        self.assertFalse(netbot.pid_alive(None))
        self.assertFalse(netbot.pid_alive(99999999))

    def status(self, pid, state, hour):
        netbot.write_state("u", state=state)
        with mock.patch.object(netbot, "running_pid", return_value=pid), \
                mock.patch.object(netbot, "invite_counts", return_value=(3, 63, 63)):
            return netbot.status("u", now=datetime(2026, 11, 20, hour, 0))

    def test_status_states(self):
        self.assertEqual(self.status(1, "çalışıyor", 10)["state"], "çalışıyor")
        self.assertEqual(self.status(1, "çalışıyor", 23)["state"], "mesai dışı")
        self.assertEqual(self.status(None, "çalışıyor", 10)["state"], "durduruldu")      # süreç ölmüş
        self.assertEqual(self.status(None, "giriş gerekli", 10)["state"], "giriş gerekli")  # neden durduğu kaybolmasın
        s = self.status(1, "beklemede", 12)
        self.assertEqual((s["state"], s["running"], s["today"], s["week"]), ("beklemede", True, 3, 63))

    def test_start_refuses_when_running(self):
        with mock.patch.object(netbot, "running_pid", return_value=42), mock.patch("subprocess.Popen") as popen:
            ok, msg = netbot.start("u")
        self.assertFalse(ok)
        popen.assert_not_called()

    def test_stop_when_not_running(self):
        with mock.patch.object(netbot, "running_pid", return_value=None):
            ok, _ = netbot.stop("u")
        self.assertFalse(ok)
        self.assertEqual(netbot.read_state("u")["state"], "durduruldu")

    def test_parse_invite(self):
        self.assertEqual(netbot.parse_invite("şirket=aselsan|bt; kişi=Serdar Sunar; url=https://x/in/s"),
                         {"Kişi": "Serdar Sunar", "Kaynak": "Aselsan · BT", "Profil": "https://x/in/s"})
        self.assertEqual(netbot.parse_invite("şirket=roketsan; kişi=Melike Özgen; url=u")["Kaynak"], "Roketsan · İK")
        self.assertEqual(netbot.parse_invite("kişi=Ayşe Kaya; url=u")["Kaynak"], "Genel arama")
        self.assertEqual(netbot.parse_invite("kişi=https://x/in/a; url=https://x/in/a")["Kişi"], "(adsız)")

    def test_recent_invites_time_format(self):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = [("2026-11-19 22:59:01", "kişi=A B; url=u")]
        with mock.patch("app.dbconn.connect", return_value=conn):
            self.assertEqual(netbot.recent_invites()[0]["Zaman"], "19.11 22:59")

    def test_recent_log_filters_noise(self):
        with open(netbot.log_path("u"), "w", encoding="utf-8") as f:
            f.write("2026-11-19 22:00:01,000 [INFO] scraper: Alakasız ilan elendi: X\n"
                    "19.11 22:27 Başladı\n"
                    "19.11 22:27 Aselsan İK {\"sent\": [], \"skipped\": [\"Aselsan: son 30 günde bu şirkete zaten davet gönderildi\"]}\n"
                    "19.11 22:30 Arama 'IT Recruiter' (hr): 5 kişi bulundu, davet: [\"A\"]\n")
        self.assertEqual(netbot.recent_log("u"), ["19.11 22:27 Başladı",
                                                  "19.11 22:30 Arama 'IT Recruiter' (hr): 5 kişi bulundu, davet: [\"A\"]"])


if __name__ == "__main__":
    unittest.main()
