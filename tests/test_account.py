"""Hesap senkronu, başarı analizi ve kod incelemesinde bulunan hataların regresyon testleri."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app import guard, account, settings
from ai_engine.form_answers import answer_for, answers_from_cv, field_key
from browser import automator as a

ANSWERS = {"email": "x@y.com", "phone": "05451112233", "city": "Ankara", "years": "4"}


class TempDB(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = guard.DB_PATH
        guard.DB_PATH = self.path

    def tearDown(self):
        guard.DB_PATH = self._orig
        os.remove(self.path)


class FormFalsePositiveTests(unittest.TestCase):
    """İnceleme #2: form doldurma cevap uydurmamalı."""

    def test_accept_concept_not_phone(self):
        for label in ("Do you accept the salary range?", "Acceptable notice period", "Concepts you know"):
            self.assertIsNone(answer_for(label, "text", ANSWERS), label)

    def test_skill_specific_years_left_to_user(self):
        for label in ("How many years of experience do you have with Kubernetes?",
                      "Kubernetes ile kaç yıl deneyiminiz var?", "Years of experience in Python"):
            self.assertIsNone(answer_for(label, "number", ANSWERS), label)

    def test_general_years_filled(self):
        self.assertEqual(answer_for("Toplam kaç yıl iş deneyiminiz var?", "number", ANSWERS), "4")
        self.assertEqual(answer_for("Years of professional experience", "text", ANSWERS), "4")

    def test_birth_place_salary_not_filled(self):
        for label in ("Doğum yeri (il)", "Doğum şehri", "Maaş beklentiniz (şehir bazında)", "Acil durum telefonu"):
            self.assertIsNone(field_key(label), label)

    def test_phone_city_still_work(self):
        self.assertEqual(answer_for("Cep telefonu", "tel", ANSWERS), "05451112233")
        self.assertEqual(answer_for("Yaşadığınız şehir", "text", ANSWERS), "Ankara")

    def test_city_prefers_address_line(self):
        cv = "Ali Veli\nİstanbul doğumlu\nAnkara, Keçiören\nali@x.com"
        self.assertEqual(answers_from_cv(cv)["city"], "Ankara")

    def test_city_ambiguous_left_empty(self):
        cv = "Ali Veli\nİstanbul ve İzmir projelerinde çalıştı\nali@x.com"
        self.assertNotIn("city", answers_from_cv(cv))


class CompanyMatchTests(unittest.TestCase):
    """İnceleme #5: şirket anahtarı kelime sınırıyla aranmalı."""

    def test_koc_not_kariyer_kocu(self):
        cards = [{"url": "u1", "text": "Ayşe\nİK Uzmanı | Kariyer Koçu\nAnkara"},
                 {"url": "u2", "text": "Mehmet\nİnsan Kaynakları Müdürü - Koç Holding\nAnkara"}]
        with mock.patch.object(a, "_already_invited", return_value=False):
            got = a.pick_hr_profiles(cards, "Koç Holding A.Ş.", limit=5)
        self.assertEqual([p["url"] for p in got], ["u2"])

    def test_first_degree_skipped(self):
        cards = [{"url": "u1", "text": "Ayşe • 1.\nİnsan Kaynakları Müdürü - ASELSAN"},
                 {"url": "u2", "text": "Can • 2.\nİnsan Kaynakları Uzmanı - ASELSAN"}]
        with mock.patch.object(a, "_already_invited", return_value=False):
            self.assertEqual([p["url"] for p in a.pick_hr_profiles(cards, "ASELSAN", limit=5)], ["u2"])
        self.assertEqual([p["url"] for p in a.filter_hr_people(cards)], ["u2"])


class ParserTests(unittest.TestCase):
    def test_name_from_title(self):
        self.assertEqual(a.name_from_title("(9) Dilek Öden | LinkedIn"), "Dilek Öden")
        self.assertEqual(a.name_from_title("LinkedIn"), "")

    def test_degree(self):
        self.assertEqual(a.degree_of("Ali • 1."), 1)
        self.assertEqual(a.degree_of("Bob · 2nd"), 2)
        self.assertIsNone(a.degree_of("Ayşe Yılmaz"))

    def test_job_id(self):
        self.assertEqual(a.linkedin_job_id("https://tr.linkedin.com/jobs/view/devops-engineer-at-obss-4296708666"),
                         "4296708666")
        self.assertEqual(a.linkedin_job_id("https://www.linkedin.com/jobs/view/4487721541/"), "4487721541")
        self.assertIsNone(a.linkedin_job_id("https://www.kariyer.net/is-ilani/x-4586667"))

    def test_tracker_counts(self):
        self.assertEqual(a.parse_tracker_counts("Kaydedildi · 0\nDevam Ediyor · 5\nBaşvuruldu · 33\nMülakat · 0"),
                         {"applied": 33, "interviews": 0, "in_progress": 5})

    def test_profile(self):
        text = ("Ayşe Örnek\n2 dakika içinde doğrulayın\nSistem-Güvenlik Uzmanı\n151 bağlantı\n"
                "Çalışmaya açık · Yalnızca kariyer uzmanları\nHenüz gönderi yayınlamadınız")
        p = a.parse_profile(text, "")
        self.assertEqual((p["verified"], p["connections"], p["open_to_work"], p["posts"], p["about"], p["skills"]),
                         (False, 151, "recruiters", 0, None, None))  # okunamayan bölüm = bilinmiyor, "yok" değil
        self.assertTrue(a.parse_profile("Ali\nHakkında\nAğ uzmanı\n500+ bağlantı", "Linux\nVMware")["about"])


class KnownPeopleTests(TempDB):
    def test_known_person_and_upgrade(self):
        account.save_known_people([{"url": "https://www.linkedin.com/in/ayse/?x=1", "name": "Ayşe"}], "pending_invite")
        self.assertTrue(account.is_known_person("https://tr.linkedin.com/in/AYSE"))
        account.save_known_people([{"url": "https://www.linkedin.com/in/ayse/", "name": "Ayşe"}], "connection")
        account.save_known_people([{"url": "https://www.linkedin.com/in/ayse/", "name": "Ayşe"}], "pending_invite")
        self.assertEqual(account.known_counts(), {"connection": 1})  # bağlantı geri 'bekleyen'e düşmez

    def test_already_invited_uses_account_data(self):
        account.save_known_people([{"url": "https://www.linkedin.com/in/bagli/", "name": "X"}], "connection")
        self.assertTrue(a._already_invited("https://www.linkedin.com/in/bagli/", ""))
        self.assertFalse(a._already_invited("https://www.linkedin.com/in/yeni/", ""))  # boş ad her şeyi eşleştirmez

    def test_acceptance_rate(self):
        for u in ("a", "b", "c", "d"):
            guard.record("LinkedIn", guard.INVITE, f"kişi={u}; url=https://www.linkedin.com/in/{u}/")
        account.save_known_people([{"url": f"https://www.linkedin.com/in/{u}", "name": u} for u in ("a",)], "connection")
        m = account.success_metrics(li={"applied": 33, "interviews": 0}, kn=None)
        self.assertEqual(m["Davet kabul oranı (bot)"], (25, "1/4"))
        self.assertEqual(m["LinkedIn başvuru → mülakat"], (0, "0/33"))


class RecommendationTests(TempDB):
    def test_weak_profile_gets_priority_advice(self):
        li = {"applied": 33, "interviews": 0, "profile": {"verified": False, "connections": 151, "skills": 0,
                                                           "about": False, "posts": 0, "open_to_work": "recruiters"}}
        unknown = {**li, "profile": {**li["profile"], "skills": None, "about": None}}
        titles_unknown = [r[1] for r in account.recommendations(li=unknown, kn=None)]
        self.assertNotIn("LinkedIn 'Yetenekler' bölümünü doldurun", titles_unknown)  # bilinmiyorsa önerme
        self.assertNotIn("'Hakkında' bölümü ekleyin", titles_unknown)
        recs = account.recommendations(li=li, kn=None, avg_score=50)
        titles = [r[1] for r in recs]
        self.assertEqual(recs[0][0], 1)
        self.assertIn("LinkedIn 'Yetenekler' bölümünü doldurun", titles)
        self.assertIn("Az ama isabetli başvuru", titles)
        self.assertIn("Hedef pozisyonları daraltın", titles)

    def test_strong_profile_few_recs(self):
        li = {"applied": 5, "interviews": 2, "profile": {"verified": True, "connections": 800, "skills": 20,
                                                          "about": True, "posts": 3, "open_to_work": "all"}}
        self.assertEqual(account.recommendations(li=li, kn=None, avg_score=70), [])


class WaitTurnTests(TempDB):
    """İnceleme #3: sayfalı işlemlerde her sayfadan önce kontrol."""

    def test_short_wait_then_ok(self):
        guard.record("LinkedIn", guard.SCRAPE, now=datetime.now() - timedelta(seconds=5))
        slept = []
        d = guard.wait_turn("LinkedIn", guard.SCRAPE, sleep=lambda s: (slept.append(s), self._shift(s)))
        self.assertTrue(d.ok)
        self.assertTrue(slept and slept[0] >= settings.MIN_SCRAPE_INTERVAL_SEC - 5)

    def test_hourly_limit_not_bypassed(self):
        for i in range(settings.MAX_HOURLY_SCRAPES):
            guard.record("LinkedIn", guard.SCRAPE, now=datetime.now() - timedelta(minutes=55 - i * 5))
        self.assertFalse(guard.wait_turn("LinkedIn", guard.SCRAPE, sleep=lambda s: None).ok)

    def _shift(self, sec):
        conn = guard._connect()
        conn.execute("UPDATE activity_log SET created_at = datetime(created_at, ?)", (f"-{int(sec) + 1} seconds",))
        conn.commit()
        conn.close()

    def test_is_blocked(self):
        self.assertFalse(guard.is_blocked("LinkedIn"))
        guard.report_block("LinkedIn", "HTTP 999")
        self.assertTrue(guard.is_blocked("LinkedIn"))

    def test_job_ad_with_429_text_not_block(self):
        self.assertIsNone(guard.detect_block("Web sunucularında 429 Too Many Requests hatalarını giderme"))


class NoDescriptionCapTests(unittest.TestCase):
    """İnceleme #6: ilan metni yoksa puan 60'ı geçmemeli."""

    def test_cap(self):
        from ai_engine import brain
        fake = {"requirements": [{"item": "Linux", "status": "var", "evidence": "Linux"}] * 4, "field_fit": 4,
                "golden_keywords": [], "missing_skills": [], "evaluation": "- iyi"}
        with mock.patch.object(brain, "_chat_json", return_value=fake), \
                mock.patch.object(brain, "_cv_for_prompt", return_value="Linux Windows Server ağ yönetimi"), \
                mock.patch.object(brain, "read_cv_text", return_value="Linux Windows Server ağ yönetimi"):
            r = brain.full_ai_analysis(1, "Sistem Yöneticisi", "Firma", "Ankara", "", save=False, brief=True)
        self.assertLessEqual(r["score_int"], 60)


class KariyerNetSyncTests(unittest.TestCase):
    CARDS = [
        {"href": "https://www.kariyer.net/is-ilani/ddy-gida-a-s-erp-uzmani-4580457", "text": "ERP Uzmanı\nBaşvurun 13.11.2026 tarihinde iletildi.\nDurumu Güncelle"},
        {"href": "https://www.kariyer.net/is-ilani/ddy-gida-a-s-erp-uzmani-4580457", "text": "ERP Uzmanı\nBaşvurun 13.11.2026 tarihinde iletildi.\nDurumu Güncelle"},
        {"href": "https://www.kariyer.net/is-ilani/bestepe-kolej-bilgi-islem-personeli-4500001", "text": "Özgeçmişin İndirildi\nDurumu Güncelle"},
        {"href": "https://www.kariyer.net/is-ilani/gurbag-bt-direktoru-4500002", "text": "Özgeçmişin Görüntülendi\nDurumu Güncelle"},
        {"href": "https://www.kariyer.net/is-ilani/x-sistem-4500003", "text": "Başvurun olumsuz sonuçlandı\nDurumu Güncelle"},
    ]

    def test_job_id(self):
        self.assertEqual(a.kariyernet_job_id("https://www.kariyer.net/is-ilani/ddy-gida-a-s-erp-uzmani-4580457"), "4580457")
        self.assertEqual(a.kariyernet_job_id("https://www.kariyer.net/is-ilani/x-4580457#sana-uygun-profil"), "4580457")

    def test_summary_dedups_and_classifies(self):
        sm = a.summarize_kariyernet(self.CARDS)
        self.assertEqual((sm["applied"], sm["sent"], sm["downloaded"], sm["viewed"], sm["rejected"]), (4, 1, 1, 2, 1))

    def test_metrics(self):
        m = account.success_metrics(li=None, kn={"applied": 20, "viewed": 3, "interview": 1})
        self.assertEqual(m["Kariyer.net başvuru → görüntülenme"], (15, "3/20"))
        self.assertEqual(m["Kariyer.net başvuru → mülakat"], (5, "1/20"))


class VolumeRecommendationTests(TempDB):
    def test_mass_applying_flagged_first(self):
        recs = account.recommendations(li=None, kn={"applied": 744, "viewed": 6, "interview": 0}, avg_score=None)
        self.assertEqual(recs[0][1], "Toplu başvuru oranı düşürüyor")


class SearchCursorTests(TempDB):
    def test_cursor(self):
        self.assertEqual(account.get_search_page("ik|ankara"), 1)
        account.set_search_page("ik|ankara", 4)
        self.assertEqual(account.get_search_page("ik|ankara"), 4)
        self.assertEqual(account.get_search_page("ik|istanbul"), 1)


if __name__ == "__main__":
    unittest.main()
