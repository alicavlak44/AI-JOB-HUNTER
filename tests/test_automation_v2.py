"""Otomatik İlan Avcısı, Akıllı Ağ Botu v2, LinkedIn /in/<slug> tekilleştirme ve mülakat oturum yükleme testleri."""
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import pandas as pd

from ai_engine import interview as iv
from app import account, jobbot, netbot
from app.settings import STATUS_ANALYZED, STATUS_APPLIED_VERIFIED, STATUS_NEW
from browser import automator as a


class LinkedInUrlDedupTests(unittest.TestCase):
    def test_norm_url_strips_profile_subpaths(self):
        base = "https://www.linkedin.com/in/simay-pektas-085a80110"
        self.assertEqual(account.norm_url(base + "/"), base)
        self.assertEqual(account.norm_url(base + "/opportunities/hiring-opportunities/view/?foo=1"), base)
        self.assertEqual(account.norm_url("https://tr.linkedin.com/in/Simay-Pektas-085a80110/overlay/photo/"), base)
        self.assertEqual(account.norm_url("u1"), "u1")

    def test_filter_hr_people_dedups_hiring_subpath(self):
        cards = [
            {"url": "https://www.linkedin.com/in/simay-pektas-085a80110/",
             "text": "Simay Pektas\n• 2.\nHR Manager & Technical Recruiter\nAnkara"},
            {"url": "https://www.linkedin.com/in/simay-pektas-085a80110/opportunities/hiring-opportunities/view/",
             "text": "Simay Pektas\n• 2.\nHR Manager & Technical Recruiter\nAnkara"},
        ]
        got = a.filter_hr_people(cards)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["url"], "https://www.linkedin.com/in/simay-pektas-085a80110")

    def test_pick_hr_profiles_dedups_hiring_subpath(self):
        cards = [
            {"url": "https://www.linkedin.com/in/ayse-123/",
             "text": "Ayşe Yılmaz\nİnsan Kaynakları Müdürü - ASELSAN\nAnkara"},
            {"url": "https://www.linkedin.com/in/ayse-123/opportunities/hiring-opportunities/view/",
             "text": "Ayşe Yılmaz\nİnsan Kaynakları Müdürü - ASELSAN\nAnkara"},
        ]
        with mock.patch.object(a, "_already_invited", return_value=False):
            got = a.pick_hr_profiles(cards, "ASELSAN", limit=5)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["url"], "https://www.linkedin.com/in/ayse-123")


class SmartNetbotTests(unittest.TestCase):
    def test_priority_companies_order_and_filtering(self):
        df = pd.DataFrame([
            {"Şirket": "Gizli Şirket", "Durum": STATUS_APPLIED_VERIFIED, "ATS Uyum": "%90"},
            {"Şirket": "Aselsan", "Durum": STATUS_APPLIED_VERIFIED, "ATS Uyum": "%70"},
            {"Şirket": "OBSS", "Durum": STATUS_ANALYZED, "ATS Uyum": "%88"},
            {"Şirket": "İnnova", "Durum": STATUS_ANALYZED, "ATS Uyum": "%76"},
            {"Şirket": "Düşük Firma", "Durum": STATUS_ANALYZED, "ATS Uyum": "%40"},
            {"Şirket": "aselsan", "Durum": STATUS_ANALYZED, "ATS Uyum": "%95"},  # zaten eklendi
        ])
        prio = netbot.priority_companies(df, min_score=65)
        self.assertEqual(prio, ["Aselsan", "OBSS", "İnnova"])

    def test_merge_companies_preserves_priority_without_dups(self):
        merged = netbot.merge_companies(["OBSS", "İnnova"], ["Aselsan", "obss", "Roketsan"])
        self.assertEqual(merged, ["OBSS", "İnnova", "Aselsan", "Roketsan"])

    def test_search_plan_by_field(self):
        roles_it, searches_it = netbot.search_plan("it")
        self.assertEqual(roles_it, ["hr", "it"])
        self.assertTrue(any("İnsan Kaynakları Müdürü" == q for q, _ in searches_it))
        roles_ik, searches_ik = netbot.search_plan("ik")
        self.assertEqual(roles_ik, ["hr"])
        self.assertTrue(all(r == "hr" for _, r in searches_ik))


class JobbotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p_logs = mock.patch.object(jobbot, "LOGS_DIR", self.tmp)
        self.p_logs.start()

    def tearDown(self):
        self.p_logs.stop()

    def test_state_roundtrip_and_status(self):
        jobbot.write_state("u", state="beklemede", found_total=12, analyzed_total=8, prepared_total=2, next_run="16:30")
        with mock.patch.object(jobbot, "running_pid", return_value=None):
            s = jobbot.status("u", now=datetime(2026, 11, 22, 15, 0))
        self.assertFalse(s["running"])
        self.assertEqual(s["state"], "durduruldu")
        self.assertEqual((s["found_total"], s["analyzed_total"], s["prepared_total"]), (12, 8, 2))

        with mock.patch.object(jobbot, "running_pid", return_value=99999):
            s_work = jobbot.status("u", now=datetime(2026, 11, 22, 15, 0))
            s_night = jobbot.status("u", now=datetime(2026, 11, 22, 2, 0))
        self.assertTrue(s_work["running"])
        self.assertEqual(s_work["state"], "beklemede")
        self.assertEqual(s_night["state"], "mesai dışı")

    def test_stop_when_not_running(self):
        with mock.patch.object(jobbot, "running_pid", return_value=None):
            ok, msg = jobbot.stop("u")
        self.assertFalse(ok)
        self.assertIn("çalışmıyor", msg)

    def test_recent_log_filters_timestamped_lines(self):
        with open(jobbot.log_path("u"), "w", encoding="utf-8") as f:
            f.write("gürültü satırı\n22.11 14:10 Tarama başladı\n22.11 14:15 3 yeni ilan\n")
        self.assertEqual(jobbot.recent_log("u", 10), ["22.11 14:10 Tarama başladı", "22.11 14:15 3 yeni ilan"])

    def test_ready_opportunities(self):
        cv_file = os.path.join(self.tmp, "cv.docx")
        with open(cv_file, "wb") as f:
            f.write(b"ok")
        df = pd.DataFrame([
            {"id": 1, "Durum": STATUS_ANALYZED, "ATS Uyum": "%84", "Şirket": "OBSS", "Pozisyon": "SysAdmin",
             "Kaynak": "LinkedIn", "cover_letter": "Merhaba, " + "x" * 60, "tailored_cv_path": cv_file, "url": "https://a"},
            {"id": 2, "Durum": STATUS_ANALYZED, "ATS Uyum": "%78", "Şirket": "STM", "Pozisyon": "Network",
             "Kaynak": "Kariyer.net", "cover_letter": "", "tailored_cv_path": "", "url": "https://b"},
            {"id": 3, "Durum": STATUS_APPLIED_VERIFIED, "ATS Uyum": "%92", "Şirket": "Aselsan", "Pozisyon": "IT",
             "Kaynak": "LinkedIn", "cover_letter": "x" * 80, "tailored_cv_path": cv_file, "url": "https://c"},
            {"id": 4, "Durum": STATUS_NEW, "ATS Uyum": "-", "Şirket": "X", "Pozisyon": "Y",
             "Kaynak": "LinkedIn", "cover_letter": "", "tailored_cv_path": "", "url": "https://d"},
        ])
        opps = jobbot.ready_opportunities(df, min_score=75)
        self.assertEqual([o["Şirket"] for o in opps], ["OBSS", "STM"])
        self.assertEqual((opps[0]["Ön yazı"], opps[0]["Özel CV"]), ("Hazır", "Hazır"))
        self.assertEqual((opps[1]["Ön yazı"], opps[1]["Özel CV"]), ("Bekliyor", "Bekliyor"))


class InterviewSessionLoadTests(unittest.TestCase):
    def test_save_list_and_load_session(self):
        d = tempfile.mkdtemp()
        with mock.patch("ai_engine.cv_studio.PROFILES_DIR", d):
            iv.save_session("u", {"title": "Ağ Yöneticisi", "report": {"overall": 82}, "results": [{"answer": "VLAN"}]})
            rows = iv.list_sessions("u")
            self.assertEqual(len(rows), 1)
            loaded = iv.load_session("u", rows[0]["file"])
        self.assertEqual(loaded["title"], "Ağ Yöneticisi")
        self.assertEqual(loaded["results"][0]["answer"], "VLAN")


if __name__ == "__main__":
    unittest.main()
