"""Başvuru takibi (CRM), takip kuyruğu, LinkedIn profil optimizasyonu (uydurmasız),
İngilizce mülakat modu ve konuşma hızı (WPM) testleri."""
import io
import os
import tempfile
import unittest
import wave
from datetime import datetime
from unittest import mock

import numpy as np
import pandas as pd

from ai_engine import interview as iv
from ai_engine import linkedin_opt, voice
from app import account, context, followup, guard
from app.settings import STATUS_ANALYZED, STATUS_APPLIED_VERIFIED
from database import db_manager as db


class FollowupAndCrmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.p_db = mock.patch.object(context, "db_path", return_value=self.db_path)
        self.p_gdb = mock.patch.object(guard, "db_file", return_value=self.db_path)
        self.p_db.start()
        self.p_gdb.start()
        db._READY.clear()
        db.init_db()

    def tearDown(self):
        self.p_db.stop()
        self.p_gdb.stop()

    def test_update_job_tracking_persists_fields(self):
        db.insert_job("LinkedIn", "Sistem Uzmanı", "Aselsan", "Ankara", "https://example.com/1")
        jobs = db.get_all_jobs()
        jid = int(jobs.iloc[0]["id"])
        db.update_job_tracking(jid, "Teknik Mülakat", "2026-11-28 14:00", "Ağ ekibiyle görüşme", mark_followed_up=True)
        row = db.get_all_jobs().iloc[0]
        self.assertEqual(row["pipeline_stage"], "Teknik Mülakat")
        self.assertEqual(row["interview_date"], "2026-11-28 14:00")
        self.assertEqual(row["notes"], "Ağ ekibiyle görüşme")
        self.assertTrue(bool(row["followed_up_at"]))

    def test_due_followups_and_upcoming_interviews(self):
        now = datetime(2026, 11, 22, 15, 0)
        df = pd.DataFrame([
            {"id": 1, "Durum": STATUS_APPLIED_VERIFIED, "Şirket": "OBSS", "Pozisyon": "SysAdmin",
             "ATS Uyum": "%85", "applied_at": "2026-11-10 10:00:00", "created_at": "2026-11-10 10:00:00",
             "pipeline_stage": "", "interview_date": "", "followed_up_at": "", "url": "https://a"},
            {"id": 2, "Durum": STATUS_APPLIED_VERIFIED, "Şirket": "STM", "Pozisyon": "Network",
             "ATS Uyum": "%92", "applied_at": "2026-11-12 10:00:00", "created_at": "2026-11-12 10:00:00",
             "pipeline_stage": "Başvuruldu", "interview_date": "", "followed_up_at": "", "url": "https://b"},
            {"id": 3, "Durum": STATUS_APPLIED_VERIFIED, "Şirket": "Yeni", "Pozisyon": "IT",
             "ATS Uyum": "%95", "applied_at": "2026-11-20 10:00:00", "created_at": "2026-11-20 10:00:00",
             "pipeline_stage": "", "interview_date": "", "followed_up_at": "", "url": "https://c"},
            {"id": 4, "Durum": STATUS_APPLIED_VERIFIED, "Şirket": "Aselsan", "Pozisyon": "Linux",
             "ATS Uyum": "%88", "applied_at": "2026-11-05 10:00:00", "created_at": "2026-11-05 10:00:00",
             "pipeline_stage": "Teknik Mülakat", "interview_date": "2026-11-25 14:00", "followed_up_at": "", "url": "https://d"},
            {"id": 5, "Durum": STATUS_ANALYZED, "Şirket": "Red", "Pozisyon": "X",
             "ATS Uyum": "%80", "applied_at": "2026-11-01 10:00:00", "created_at": "2026-11-01 10:00:00",
             "pipeline_stage": "Olumsuz", "interview_date": "2026-11-29 10:00", "followed_up_at": "", "url": "https://e"},
        ])
        due = followup.due_followups(df, days=7, now=now)
        self.assertEqual([d["Şirket"] for d in due], ["STM", "OBSS"])
        upcoming = followup.upcoming_interviews(df, now=now)
        self.assertEqual([u["Şirket"] for u in upcoming], ["Aselsan"])

    def test_accepted_contacts_cross_reference(self):
        guard.record("LinkedIn", guard.INVITE,
                     "şirket=aselsan; kişi=Ayşe Yılmaz; url=https://www.linkedin.com/in/ayse-yilmaz/")
        guard.record("LinkedIn", guard.INVITE,
                     "şirket=stm; kişi=Can Demir; url=https://www.linkedin.com/in/can-demir/")
        account.save_known_people([
            {"url": "https://www.linkedin.com/in/ayse-yilmaz/opportunities/hiring-opportunities/view/", "name": "Ayşe Yılmaz"},
        ], "connection")
        acc = followup.accepted_contacts()
        self.assertEqual(len(acc), 1)
        self.assertEqual(acc[0]["Kişi"], "Ayşe Yılmaz")
        self.assertIn("Aselsan", acc[0]["Kaynak"])

    def test_messages(self):
        m = followup.followup_message("Sistem Uzmanı", "Aselsan", "Ali Cavlak", days_ago=10)
        self.assertIn("Aselsan", m)
        self.assertIn("10 gün önce", m)
        self.assertIn("Ali Cavlak", m)
        w = followup.welcome_connection_message("Satiye Koç", "Ali Cavlak", "Sistem Yöneticisi")
        self.assertIn("Satiye", w)
        self.assertIn("Sistem Yöneticisi", w)


class LinkedInOptTests(unittest.TestCase):
    PROFILE = {
        "name": "Ali Cavlak",
        "headline": "Sistem ve Ağ Yöneticisi",
        "summary": "Linux, Cisco ve FortiGate tabanlı kurumsal ağ altyapılarını yönetiyorum.",
        "skills": [{"group": "Ağ", "items": ["Cisco", "VLAN", "FortiGate", "Linux", "Active Directory"]}],
        "experience": [{"title": "Sistem Yöneticisi", "company": "X A.Ş.", "dates": "2022 - 2025",
                        "bullets": [{"text": "300 kullanıcılı kurumsal ağı yönettim.", "user": False}]}],
    }
    CV = "Ali Cavlak Sistem ve Ağ Yöneticisi Linux Cisco VLAN FortiGate Active Directory 300 kullanıcılı ağı yönettim."

    def test_rule_pack_no_ai(self):
        pack = linkedin_opt.generate_linkedin_pack(self.PROFILE, self.CV, field="it", use_ai=False)
        self.assertEqual(pack["source"], "kural")
        self.assertTrue(all(len(h) <= 220 for h in pack["headlines"]))
        self.assertIn("Cisco", pack["skills"])
        self.assertIn("300", pack["about_tr"])

    def test_ai_hallucination_rejected(self):
        fake = {
            "headlines": [
                "Sistem ve Ağ Yöneticisi | Cisco, FortiGate, Linux",
                "Kubernetes & Terraform Principal Architect",  # uydurma → reddedilmeli
            ],
            "about_tr": "300 kullanıcılı Linux ve Cisco altyapısını yönetiyorum.",
            "about_en": "I managed 5000 AWS Lambda functions.",  # uydurma → reddedilmeli
        }
        with mock.patch("ai_engine.brain._chat_json", return_value=fake):
            pack = linkedin_opt.generate_linkedin_pack(self.PROFILE, self.CV, field="it", use_ai=True)
        self.assertEqual(pack["source"], "yapay zekâ")
        self.assertEqual(len(pack["headlines"]), 1)
        self.assertIn("Cisco", pack["headlines"][0])
        self.assertIn("300", pack["about_tr"])
        self.assertEqual(pack["about_en"], "")
        self.assertGreaterEqual(len(pack["rejected"]), 2)


class InterviewEnAndWpmTests(unittest.TestCase):
    PROFILE = {"name": "Ali", "headline": "System Administrator", "summary": "", "skills": [], "experience": []}

    def test_english_bank_plan(self):
        qs, err = iv.plan_interview(self.PROFILE, "it", n_tech=2, n_beh=1, use_ai=False, lang="en")
        self.assertIsNone(err)
        self.assertEqual(len(qs), 6)
        self.assertIn("background", qs[0]["question"].lower())
        self.assertTrue(all(q["question"].endswith("?") for q in qs))

    def test_wpm_signals_and_report(self):
        q = {"stage": "technical", "question": "VLAN nedir?", "expects": "802.1Q"}
        ans = " ".join(["kelime"] * 60) + " 300"
        ev = iv.evaluate(q, ans, self.PROFILE, use_ai=False, duration_sec=30.0)
        self.assertEqual(ev["signals"]["duration_sec"], 30.0)
        self.assertEqual(ev["signals"]["wpm"], 122)  # 61 words / 0.5 min = 122
        rep = iv.report([{"question": q, "answer": ans, "eval": ev}])
        self.assertEqual(rep["duration_sec"], 30.0)
        self.assertEqual(rep["avg_wpm"], 122)

    def test_transcribe_with_stats_short_wav(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(np.zeros(4000, dtype=np.int16).tobytes())  # 0.25 sn
        with mock.patch.object(voice, "stt_available", return_value=True), \
                mock.patch.dict("sys.modules", {"mlx_whisper": mock.MagicMock()}):
            res = voice.transcribe_with_stats(buf.getvalue(), language="en")
        self.assertEqual(res["text"], "")
        self.assertAlmostEqual(res["duration_sec"], 0.2, delta=0.1)


if __name__ == "__main__":
    unittest.main()
