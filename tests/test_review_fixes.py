"""2026-11-19 dış inceleme raporunda doğrulanan hataların regresyon testleri (model / internet gerektirmez)."""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from ai_engine import cv_profile
from ai_engine.cv_builder import parse_cv, parsed_from_profile, profile_text, tr_title

# CV Stüdyosu PDF'inden çıkan metin biçimi: madde işareti yok, unvan + tarih aynı satır, ad normal yazım
STUDIO_TEXT = """Ayşe Yılmaz
Sistem Yöneticisi | Ağ Güvenliği
ayse@ornek.com · 0 (532) 000 00 00 · Ankara
ÖZET
Kurumsal ağ ve sunucu altyapısı yöneten sistem yöneticisi.
DENEYİM
Sistem Yöneticisi Ocak 2022 – Günümüz
ÖRNEK TEKNOLOJİ A.Ş. · Ankara
300 kullanıcılı ağı ve 40 sunucuyu yönettim.
Firewall kurallarını yeniden düzenleyerek
erişim sorunlarını azalttım.
BT Stajyeri Temmuz 2020 – Ağustos 2020
DENEME LTD. · İstanbul
Kullanıcılara destek verdim.
BECERİLER
Ağ: Cisco, VLAN
EĞİTİM
Bilgisayar Programcılığı · Ankara Üniversitesi · 2021
"""


class StudioPdfParseTests(unittest.TestCase):
    """1) CV Stüdyosu PDF'leri ilana özel CV üreticisini bozuyordu (ad boş, 0 deneyim)."""

    def test_studio_layout_is_parsed(self):
        cv = parse_cv(STUDIO_TEXT)
        self.assertEqual(cv.name, "Ayşe Yılmaz")
        self.assertTrue(cv.headline.startswith("Sistem Yöneticisi"))
        self.assertEqual([e.title for e in cv.experience], ["Sistem Yöneticisi", "BT Stajyeri"])
        self.assertEqual(cv.experience[0].company, "ÖRNEK TEKNOLOJİ A.Ş.")
        self.assertEqual(cv.experience[0].city, "Ankara")
        self.assertEqual([b.text for b in cv.experience[0].bullets],
                         ["300 kullanıcılı ağı ve 40 sunucuyu yönettim.",
                          "Firewall kurallarını yeniden düzenleyerek erişim sorunlarını azalttım."])
        self.assertEqual(len(cv.skill_groups), 1)

    def test_turkish_uppercase_section_names(self):
        cv = parse_cv("ALİ VELİ\nUzman\nDENEYİM\nUzman\nX A.Ş.\nOcak 2020 - Mart 2021\n• Bir iş yaptım.\nBECERİLER\nAğ: VLAN\n")
        self.assertEqual(len(cv.experience), 1)
        self.assertEqual(len(cv.skill_groups), 1)

    def test_profile_is_used_losslessly(self):
        p = {"name": "Ayşe Yılmaz", "headline": "Sistem Yöneticisi", "email": "a@b.com", "summary": "Özet.",
             "skills": [{"group": "Ağ", "items": ["Cisco", "VLAN"]}],
             "experience": [{"title": "Sistem Yöneticisi", "company": "X", "city": "Ankara", "dates": "Ocak 2022 – Günümüz",
                             "bullets": [{"text": "40 sunucuyu yönettim.", "user": False},
                                         {"text": "VPN kurdum.", "user": True}]}],
             "education": ["Bilgisayar Programcılığı"], "certificates": [], "languages": "İngilizce B1",
             "extras": ["B sınıfı ehliyet"], "links": []}
        cv = parsed_from_profile(p)
        self.assertEqual(cv.experience[0].id, "E1")
        self.assertEqual([b.id for b in cv.experience[0].bullets], ["E1.B1", "E1.B2"])
        self.assertEqual(cv.skill_groups, [("Ağ", ["Cisco", "VLAN"])])
        text = profile_text(p)
        for part in ("40 sunucuyu yönettim.", "VPN kurdum.", "Ağ: Cisco, VLAN", "İngilizce B1", "Ocak 2022 – Günümüz"):
            self.assertIn(part, text)


class TurkishNameTests(unittest.TestCase):
    """5) str.title() Türkçede bozuk: 'ALİ' → 'Ali̇', 'IŞIK' → 'Işik'."""

    def test_tr_title(self):
        self.assertEqual(tr_title("ALİ IŞIK"), "Ali Işık")
        self.assertEqual(tr_title("İPEK ÇİÇEK"), "İpek Çiçek")


class PeriodFormatTests(unittest.TestCase):
    """6) Deneyim yılı yalnızca 'Ocak 2022 - Mart 2024' biçiminde hesaplanıyordu."""

    def years(self, line):
        return round(cv_profile.build_profile(f"Deneyim\nSistem Uzmanı\n{line}", today=date(2026, 11, 1))
                     .professional_months / 12, 1)

    def test_formats(self):
        for line in ("Ocak 2022 - Mart 2024", "01/2022 - 03/2024", "01.2022 - 03.2024", "Oca 2022 - Mar 2024",
                     "Jan 2022 – Mar 2024"):
            self.assertEqual(self.years(line), 2.2, line)
        self.assertEqual(self.years("2020 - 2024"), 4.1)

    def test_internship_on_same_line_is_not_professional(self):
        text = "Deneyim\nBT Stajyeri Temmuz 2021 – Ağustos 2021\nSistem Uzmanı Ocak 2022 – Ocak 2024\n"
        self.assertEqual(round(cv_profile.build_profile(text).professional_months / 12, 1), 2.1)

    def test_month_of(self):
        self.assertEqual(cv_profile.month_of("Ağu"), 8)
        self.assertEqual(cv_profile.month_of("12/"), 12)
        self.assertEqual(cv_profile.month_of(None), 1)
        self.assertEqual(cv_profile.month_of("xyz"), 1)


class ExtraProfileTests(unittest.TestCase):
    """3) Ayarlar'daki ehliyet/askerlik/seyahat cevapları ilan analizine ulaşmıyordu."""

    def test_interpret(self):
        ia = cv_profile.interpret_answer
        self.assertTrue(ia("driving_license", "B sınıfı var"))
        self.assertFalse(ia("driving_license", "Yok"))
        self.assertTrue(ia("military_done", "Muaf"))
        self.assertIsNone(ia("military_done", "Tecilli"))   # emin değilse iddia edilmez
        self.assertTrue(ia("can_travel", "Ankara içi, seyahate engel yok"))
        self.assertFalse(ia("can_travel", "Hayır"))

    def test_form_answers_reach_matcher(self):
        user = {"form_answers": {"license": "B sınıfı var", "military": "Yapıldı"}}
        with mock.patch("app.context.user", return_value=user), \
                mock.patch("ai_engine.cv_studio.load_profile", side_effect=FileNotFoundError), \
                mock.patch.object(cv_profile, "_read_extra_file", return_value={"night_shift_ok": None}):
            extra = cv_profile.load_extra_profile()
        self.assertEqual(extra, {"driving_license": True, "military_done": True})

    def test_explicit_file_wins(self):
        with mock.patch("app.context.user", return_value={"form_answers": {"license": "B sınıfı var"}}), \
                mock.patch("ai_engine.cv_studio.load_profile", side_effect=FileNotFoundError), \
                mock.patch.object(cv_profile, "_read_extra_file", return_value={"driving_license": False}):
            self.assertEqual(cv_profile.load_extra_profile(), {"driving_license": False})


class FakePage:
    def __init__(self, confirm_after=None, close_after=None):
        self.n, self.confirm_after, self.close_after = 0, confirm_after, close_after

    def is_closed(self):
        return self.close_after is not None and self.n >= self.close_after

    def wait_for_timeout(self, ms):
        self.n += 1


class WaitUserFinishTests(unittest.TestCase):
    """2) Tam otonomda kullanıcı formu tamamlasa da 'Doğrulandı' olmuyordu."""

    def run_wait(self, page, timeout_ms=30_000):
        from browser import automator
        with mock.patch.object(automator, "_is_confirmed", side_effect=lambda p, b: p.confirm_after is not None
                               and p.n >= p.confirm_after):
            return automator._wait_user_finish(page, set(), timeout_ms, poll_ms=1000)

    def test_confirmation_seen_before_close(self):
        self.assertTrue(self.run_wait(FakePage(confirm_after=2, close_after=5)))

    def test_closed_without_confirmation(self):
        self.assertFalse(self.run_wait(FakePage(close_after=3)))

    def test_timeout(self):
        self.assertFalse(self.run_wait(FakePage(), timeout_ms=5000))


class ProfileLockTests(unittest.TestCase):
    """4) Panel ve arka plan botu aynı Chrome profilini aynı anda açıyordu."""

    def test_second_opener_waits_then_fails(self):
        from browser import automator
        from playwright.sync_api import Error as PlaywrightError
        d = tempfile.mkdtemp()
        prof = os.path.join(d, "bot_profile")
        with automator._profile_lock(prof, wait=0):
            with self.assertRaises(PlaywrightError):
                with automator._profile_lock(prof, wait=0.5):
                    pass
        with automator._profile_lock(prof, wait=0):  # kilit bırakıldıktan sonra açılabilir
            pass


class DbTests(unittest.TestCase):
    def test_wal_mode(self):
        from app import dbconn
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        conn = dbconn.connect(path)
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        conn.close()


class QaMemoryTests(unittest.TestCase):
    """7) Soru hafızasında silinen satır hafızadan silinmiyordu."""

    def test_removed_rows(self):
        from app import context
        users = {"u": {"qa": {"linux biliyor musunuz": "Evet", "kubernetes": "Hayır"}, "qa_pending": ["Vardiya?"]}}
        saved = {}
        with mock.patch.object(context, "load_users", return_value=users), \
                mock.patch.object(context, "save_users", side_effect=lambda u: saved.update(u)):
            context.set_answers({"Linux biliyor musunuz": "Evet"}, slug="u", removed=["Kubernetes", "Vardiya?"])
        self.assertEqual(saved["u"]["qa"], {"linux biliyor musunuz": "Evet"})
        self.assertEqual(saved["u"]["qa_pending"], [])


if __name__ == "__main__":
    unittest.main()
