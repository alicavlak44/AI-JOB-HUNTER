"""Kadro sınıfı (Tekniker / Uzman / Mühendis) ve Yeni Mezun / Junior sınıflandırması testleri."""
import unittest

import pandas as pd

from ai_engine.role_class import (
    ROLE_ENG, ROLE_SPEC, ROLE_TECH,
    classify_role, detect_candidate_role_profile, matches_role_prefs,
)
from app import campaign, jobbot
from app.settings import STATUS_ANALYZED
from browser.scraper import is_blacklisted


class RoleClassTests(unittest.TestCase):
    def test_detect_non_engineer_technician_cv(self):
        cv = """ALİ CAVLAK
Bilgi İşlem Teknikeri (Ağ ve Sistem Yöneticisi)
2023 - Devam
Eğitim
Karabük Üniversitesi — Bilgi Güvenliği Teknolojisi (Ön Lisans)"""
        rp = detect_candidate_role_profile(cv)
        self.assertFalse(rp["is_engineer"])
        self.assertTrue(rp["is_technician"])
        self.assertIn(ROLE_TECH, rp["suggested_classes"])
        self.assertIn(ROLE_SPEC, rp["suggested_classes"])
        self.assertNotIn(ROLE_ENG, rp["suggested_classes"])

    def test_detect_engineer_cv(self):
        cv = """AYŞE YILMAZ
Bilgisayar Mühendisliği (Lisans) — ODTÜ
Ağ Mühendisi 2022 - 2025"""
        rp = detect_candidate_role_profile(cv)
        self.assertTrue(rp["is_engineer"])
        self.assertIn(ROLE_ENG, rp["suggested_classes"])

    def test_classify_role_and_fresh_grad(self):
        self.assertEqual(classify_role("Bilgi İşlem Teknikeri")["role_class"], ROLE_TECH)
        self.assertEqual(classify_role("Sistem ve Yedekleme Uzmanı")["role_class"], ROLE_SPEC)
        self.assertEqual(classify_role("Sistem Test ve Değerlendirme Mühendisi")["role_class"], ROLE_ENG)

        fg_eng = classify_role("Yeni Mezun Yazılım Mühendisi")
        self.assertEqual(fg_eng["role_class"], ROLE_ENG)
        self.assertTrue(fg_eng["is_fresh_grad"])
        self.assertIn("Yeni Mezun", fg_eng["display"])

        fg_spec = classify_role("Bilgi İşlem Uzmanı", "Yetiştirilmek üzere, 0-2 yıl deneyimli adaylar.")
        self.assertEqual(fg_spec["role_class"], ROLE_SPEC)
        self.assertTrue(fg_spec["is_fresh_grad"])

    def test_matches_role_prefs_blocks_eng_degree_when_non_engineer(self):
        non_eng = [ROLE_TECH, ROLE_SPEC]
        self.assertTrue(matches_role_prefs("Sistem ve Ağ Uzmanı", "Ön lisans veya lisans mezunu", non_eng))
        self.assertFalse(matches_role_prefs("Network Engineer", "Cisco", non_eng))
        # Başlığı 'Uzman' olsa bile metninde açık mühendislik diploması şartı varsa elenir
        self.assertFalse(matches_role_prefs("Ağ Uzmanı", "4 yıllık mühendislik fakültesi mezunu olmak", non_eng))
        self.assertTrue(matches_role_prefs("Yeni Mezun Bilgi İşlem Teknikeri", "", non_eng, fresh_grad_only=True))
        self.assertFalse(matches_role_prefs("Kıdemli Bilgi İşlem Uzmanı", "5 yıl deneyim", non_eng, fresh_grad_only=True))

    def test_defense_mechanical_hardware_blacklisted_for_it(self):
        self.assertTrue(is_blacklisted("Ulaşım Sistemleri Mekanik Tasarım Mühendisi", field="it"))
        self.assertTrue(is_blacklisted("Elektronik Donanım Tasarım Mühendisi", field="it"))
        self.assertTrue(is_blacklisted("Hava Savunma Sistemleri Proje Mühendisi", field="it"))
        self.assertFalse(is_blacklisted("Sistem ve Yedekleme Uzmanı", field="it"))
        self.assertFalse(is_blacklisted("Bilgi İşlem Teknikeri", field="it"))

    def test_campaign_and_jobbot_respect_role_filter(self):
        df = pd.DataFrame([
            {"id": 1, "Durum": STATUS_ANALYZED, "ATS Uyum": "%82", "recommendation": "Başvur",
             "Şirket": "Aselsan", "Pozisyon": "Sistem Test Mühendisi", "Kaynak": "LinkedIn", "Şehir": "Ankara",
             "details": "Mühendislik fakültesi", "cover_letter": "", "tailored_cv_path": "", "url": "https://a"},
            {"id": 2, "Durum": STATUS_ANALYZED, "ATS Uyum": "%84", "recommendation": "Başvur",
             "Şirket": "Hidromek", "Pozisyon": "Sistem ve Yedekleme Uzmanı", "Kaynak": "Kariyer.net", "Şehir": "Ankara",
             "details": "Veeam, Linux, AD", "cover_letter": "", "tailored_cv_path": "", "url": "https://b"},
            {"id": 3, "Durum": STATUS_ANALYZED, "ATS Uyum": "%79", "recommendation": "Başvur",
             "Şirket": "Ziraat Teknoloji", "Pozisyon": "Yeni Mezun Bilgi İşlem Teknikeri", "Kaynak": "LinkedIn", "Şehir": "Ankara",
             "details": "Yeni mezun, ağ destek", "cover_letter": "", "tailored_cv_path": "", "url": "https://c"},
        ])
        got = campaign.eligible_jobs(df, min_score=65, allowed_roles=[ROLE_TECH, ROLE_SPEC])
        self.assertEqual(list(got["Şirket"]), ["Hidromek", "Ziraat Teknoloji"])
        fg = campaign.eligible_jobs(df, min_score=65, allowed_roles=[ROLE_TECH, ROLE_SPEC], fresh_grad_only=True)
        self.assertEqual(list(fg["Şirket"]), ["Ziraat Teknoloji"])
        opps = jobbot.ready_opportunities(df, min_score=75, allowed_roles=[ROLE_TECH, ROLE_SPEC])
        self.assertEqual([o["Şirket"] for o in opps], ["Hidromek", "Ziraat Teknoloji"])


if __name__ == "__main__":
    unittest.main()
