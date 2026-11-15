"""Toplu başvuru, form cevapları ve İK seçimi testleri (tarayıcı/ağ kullanılmaz)."""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import pandas as pd

from app import guard, campaign, settings
from app.settings import STATUS_ANALYZED, STATUS_NEW, STATUS_APPLIED_VERIFIED
from ai_engine.form_answers import answers_from_cv, answer_for, field_key
from browser.automator import pick_hr_profiles, company_key

CV = """Kişisel Bilgiler
ornek.aday@gmail.com
0 (545) 111 22 33
Ankara, Keçiören
Deneyim
Ağ ve Sistem Yöneticisi
Ocak 2020 - Ocak 2024
"""


class TempDB(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = guard.DB_PATH
        guard.DB_PATH = self.path

    def tearDown(self):
        guard.DB_PATH = self._orig
        os.remove(self.path)


def _df():
    rows = [
        (1, STATUS_ANALYZED, "%80", "Başvur"),
        (2, STATUS_ANALYZED, "%60", "Değerlendir"),
        (3, STATUS_ANALYZED, "%90", "Başvurma"),
        (4, STATUS_NEW, "-", None),
        (5, STATUS_APPLIED_VERIFIED, "%95", "Başvur"),
        (6, STATUS_ANALYZED, "%70", "Başvur"),
        (7, STATUS_ANALYZED, "%98  \n(Altın ke", None),  # eski sürüm analizi: önerisi yok → alınmaz
    ]
    return pd.DataFrame([dict(id=i, Durum=s, **{"ATS Uyum": sc}, recommendation=rec, Kaynak="LinkedIn",
                              Şirket=f"Firma {i}", Pozisyon="Sistem Yöneticisi", Şehir="Ankara",
                              url=f"https://www.linkedin.com/jobs/view/{i}", tailored_cv_path=None, details="")
                         for i, s, sc, rec in rows])


class EligibleTests(unittest.TestCase):
    def test_filters_and_sorts(self):
        self.assertEqual(campaign.eligible_jobs(_df(), 65)["id"].tolist(), [1, 6])

    def test_lower_threshold(self):
        self.assertEqual(campaign.eligible_jobs(_df(), 50)["id"].tolist(), [1, 6, 2])

    def test_unanalyzed(self):
        self.assertEqual(campaign.unanalyzed_jobs(_df())["id"].tolist(), [4])


class CampaignTests(TempDB):
    def _rows(self, ids):
        df = _df()
        return [r.to_dict() for _, r in df[df["id"].isin(ids)].iterrows()]

    def test_applies_only_given_rows_and_invites_each_company_once(self):
        applied, invited = [], []

        def apply_fn(job_id, url, mode, cv):
            applied.append(job_id)
            guard.record("LinkedIn", guard.APPLY, f"job {job_id}")
            return STATUS_APPLIED_VERIFIED, "ok"

        def invite_fn(company, city):
            invited.append(company)
            return {"sent": ["Ayşe Y."], "skipped": [], "error": None}

        rows = self._rows([1, 6])
        rows[1]["Şirket"] = rows[0]["Şirket"]  # aynı şirket iki ilan
        waits = []

        def fake_sleep(sec):  # zamanı ilerletmek yerine kayıtları geriye kaydır
            waits.append(sec)
            conn = guard._connect()
            conn.execute("UPDATE activity_log SET created_at = datetime(created_at, ?)", (f"-{int(sec) + 1} seconds",))
            conn.commit()
            conn.close()

        res = campaign.run_campaign(rows, apply_fn=apply_fn, invite_fn=invite_fn, sleep=fake_sleep)
        self.assertEqual(applied, [1, 6])
        self.assertEqual(invited, ["Firma 1"])
        self.assertIn("Davet gönderildi", res[0]["İK"])
        self.assertIn("zaten davet", res[1]["İK"])
        # ikinci başvurudan önce en az bekleme süresi + ilanlar arası mola uygulandı
        # (sahte saat kayıtları saniyeye yuvarladığı için 2 sn tolerans)
        self.assertGreaterEqual(sum(waits), settings.MIN_APPLY_INTERVAL_SEC - 2)

    def test_postpones_when_daily_limit_full(self):
        now = datetime.now()
        for i in range(settings.MAX_DAILY_APPLICATIONS):
            guard.record("LinkedIn", guard.APPLY, now=now - timedelta(hours=2 + i))
        called = []
        res = campaign.run_campaign(self._rows([1]), apply_fn=lambda *a: called.append(a),
                                    invite_fn=lambda *a: called.append(a), sleep=lambda s: None)
        self.assertEqual(called, [])
        self.assertTrue(res[0]["Başvuru"].startswith(campaign.POSTPONED))

    def test_block_stops_invites(self):
        invited = []
        def apply_fn(*a):  # gerçek bot gibi: engeli koruma kaydına yazar, mesajda "uyarı" kelimesi yok
            guard.report_block("LinkedIn", "doğrulama sayfası (/checkpoint/challenge)")
            return None, "🛡️ LinkedIn bot koruması belirtisi gösterdi (doğrulama sayfası)."

        res = campaign.run_campaign(self._rows([1]), apply_fn=apply_fn,
                                    invite_fn=lambda *a: invited.append(a), sleep=lambda s: None)
        self.assertEqual(invited, [])
        self.assertIn("🛡️", res[0]["Başvuru"])


class FormAnswerTests(unittest.TestCase):
    def test_answers_from_cv(self):
        a = answers_from_cv(CV, today=date(2026, 11, 15))
        self.assertEqual(a["email"], "ornek.aday@gmail.com")
        self.assertEqual(a["phone"], "05451112233")
        self.assertEqual(a["city"], "Ankara")
        self.assertEqual(a["years"], "4")

    def test_field_keys(self):
        self.assertEqual(field_key("Cep telefonu numarası"), "phone")
        self.assertEqual(field_key("E-posta adresi"), "email")
        self.assertEqual(field_key("How many years of work experience do you have with Linux?"), "years")
        self.assertEqual(field_key("Konum (şehir)"), "city")
        self.assertIsNone(field_key("Maaş beklentiniz nedir?"))  # bilinmeyen → kullanıcıya kalır

    def test_answer_respects_input_type(self):
        a = {"email": "x@y.com", "phone": "05451112233", "city": "Ankara", "years": "4"}
        self.assertEqual(answer_for("Kaç yıl deneyiminiz var?", "number", a), "4")
        self.assertIsNone(answer_for("Telefon", "number", a))  # sayı alanına telefon yazma
        self.assertIsNone(answer_for("Maaş beklentisi", "number", a))
        self.assertIsNone(answer_for("Telefon", "text", {}))  # CV'de yoksa uydurma


class HRPickTests(unittest.TestCase):
    CARDS = [
        {"url": "u1", "text": "Ayşe Yılmaz\nİnsan Kaynakları Müdürü - ASELSAN\nAnkara"},
        {"url": "u2", "text": "Mehmet Kaya\nYazılım Mühendisi - ASELSAN\nAnkara"},
        {"url": "u3", "text": "Zeynep Ak\nİK Uzmanı - Başka Firma\nAnkara"},
        {"url": "u4", "text": "Ali Veli\nTalent Acquisition Partner at Aselsan\nBeklemede"},
        {"url": "u5", "text": "Can Er\nHR Business Partner | ASELSAN"},
    ]

    def test_company_key(self):
        self.assertEqual(company_key("ASELSAN A.Ş."), "aselsan")
        self.assertEqual(company_key("Ankara Otomotiv San. Ltd. Şti."), "ankara otomotiv")

    def test_only_company_hr_not_pending(self):
        self.assertEqual([p["url"] for p in pick_hr_profiles(self.CARDS, "ASELSAN A.Ş.", limit=5)], ["u1", "u5"])

    def test_limit(self):
        self.assertEqual(len(pick_hr_profiles(self.CARDS, "ASELSAN", limit=1)), 1)

    def test_city_word_does_not_match_every_card(self):
        self.assertEqual(pick_hr_profiles(self.CARDS, "Ankara Otomotiv", limit=5), [])


class GuardDedupTests(TempDB):
    def test_done_recently(self):
        guard.record("LinkedIn", guard.INVITE, "şirket=aselsan; kişi=Ayşe")
        self.assertTrue(guard.done_recently("LinkedIn", guard.INVITE, "şirket=aselsan;"))
        self.assertFalse(guard.done_recently("LinkedIn", guard.INVITE, "şirket=havelsan;"))

    def test_detect_block_on_python_lowered_text(self):
        # automator._page_text() Python .lower() kullanır: 'İ' → 'i' + U+0307
        self.assertIsNotNone(guard.detect_block("Hesabınızda OLAĞANDIŞI ETKİNLİK".lower()))



class HRPeopleTests(unittest.TestCase):
    CARDS = [
        {"url": "u1", "text": "Dilek Öden • 2.\n2.\nİnsan Kaynakları Müdürü\nAnkara, Türkiye\nMesut S. ortak bağlantınız"},
        {"url": "u2", "text": "Ahmet Yazılımcı • 2.\nSenior Software Engineer\nAnkara, Türkiye"},
        {"url": "u3", "text": "Ece Kaya • 3.\nTalent Acquisition Specialist\nAnkara\nBeklemede"},
        {"url": "u4", "text": "Kerim ÖZTÜRK • 2.\nİnsan Kaynakları Uzmanı\nAnkara, Türkiye"},
        {"url": "u1", "text": "Dilek Öden"},  # aynı kişi iki kez
    ]

    def test_parse_card(self):
        from browser.automator import parse_person_card
        p = parse_person_card(self.CARDS[0])
        self.assertEqual((p["name"], p["headline"], p["location"]),
                         ("Dilek Öden", "İnsan Kaynakları Müdürü", "Ankara, Türkiye"))

    def test_filter_hr_people(self):
        from browser.automator import filter_hr_people
        got = filter_hr_people(self.CARDS, seen=lambda url, name: url == "u4")
        self.assertEqual([p["url"] for p in got], ["u1"])  # yazılımcı, beklemede ve daha önce davet edilen çıkar


class AlreadyInvitedTests(TempDB):
    def test_by_url(self):
        from browser.automator import _already_invited
        guard.record("LinkedIn", guard.INVITE, "kişi=Dilek Öden; url=https://x/in/dilek/")
        self.assertTrue(_already_invited("https://x/in/dilek/", "Başka Ad"))
        self.assertFalse(_already_invited("https://x/in/baska/", "Zeynep Ak"))


class SessionStatusTests(unittest.TestCase):
    def _profile(self, cookies):
        import sqlite3
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        os.makedirs(os.path.join(d, "Default"))
        conn = sqlite3.connect(os.path.join(d, "Default", "Cookies"))
        conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, expires_utc INTEGER)")
        conn.executemany("INSERT INTO cookies VALUES (?,?,'',?)", cookies)
        conn.commit()
        conn.close()
        return d

    @staticmethod
    def _chrome_time(unix):
        return int((unix + 11644473600) * 1_000_000)

    def test_detects_valid_and_expired(self):
        from browser.automator import session_status
        now = 1_800_000_000
        d = self._profile([(".www.linkedin.com", "li_at", self._chrome_time(now + 86400)),
                           (".kariyer.net", "refresh_token", self._chrome_time(now - 10))])
        self.assertEqual(session_status(d, now), {"LinkedIn": True, "Kariyer.net": False})

    def test_session_cookie_without_expiry_counts(self):
        from browser.automator import session_status
        d = self._profile([(".kariyer.net", "refresh_token", 0)])
        self.assertTrue(session_status(d)["Kariyer.net"])

    def test_missing_profile(self):
        from browser.automator import session_status
        self.assertEqual(session_status("/yok/boyle/bir/klasor"), {"LinkedIn": False, "Kariyer.net": False})


if __name__ == "__main__":
    unittest.main()
