"""Şirket ölçeği/kurumsallık sınıflandırması ve büyük şirket filtresi testleri."""
import unittest

import pandas as pd

from ai_engine.company_tier import TIER_LARGE, TIER_MEDIUM, TIER_SMALL, classify_company
from app import campaign, jobbot
from app.settings import STATUS_ANALYZED


class CompanyTierTests(unittest.TestCase):
    def test_known_enterprise_companies(self):
        for comp in ("ASELSAN", "Roketsan A.Ş.", "Ziraat Teknoloji", "İnnova Bilişim", "Siemens Türkiye", "OBSS", "Başkent Doğalgaz Dağıtım GYO A.Ş."):
            res = classify_company(comp)
            self.assertEqual(res["tier"], TIER_LARGE, f"{comp} büyük/kurumsal olmalı")
            self.assertTrue(res["is_large"])

    def test_small_or_risky_signals_flagged(self):
        self.assertEqual(classify_company("XYZ Ajans", "Küçük bir ekip içinde startup ortamı")["tier"], TIER_SMALL)
        self.assertEqual(classify_company("Örnek Ltd", "3 aylık proje, dönemsel destek")["tier"], TIER_SMALL)
        self.assertEqual(classify_company("Butik Teknoloji", "Aile şirketi ortamında tek kişilik IT")["tier"], TIER_SMALL)

    def test_large_scale_description_signals(self):
        res = classify_company("Bilinmeyen Sanayi A.Ş.", "1500+ çalışanı, ISO 27001 veri merkezi ve Ar-Ge merkezi bulunan kurumsal grup.")
        self.assertEqual(res["tier"], TIER_LARGE)

    def test_unknown_or_hidden_company_is_medium(self):
        self.assertEqual(classify_company("Gizli Şirket", "Sistem yönetimi yapılacaktır.")["tier"], TIER_MEDIUM)
        self.assertEqual(classify_company("Deneme Teknoloji Ltd.", "Ağ kurulumu")["tier"], TIER_MEDIUM)

    def test_eligible_jobs_and_ready_opportunities_only_large(self):
        df = pd.DataFrame([
            {"id": 1, "Durum": STATUS_ANALYZED, "ATS Uyum": "%82", "recommendation": "Başvur",
             "Şirket": "Aselsan", "Pozisyon": "Sistem Uzmanı", "Kaynak": "LinkedIn", "Şehir": "Ankara",
             "details": "Kurumsal altyapı", "cover_letter": "", "tailored_cv_path": "", "url": "https://a"},
            {"id": 2, "Durum": STATUS_ANALYZED, "ATS Uyum": "%88", "recommendation": "Başvur",
             "Şirket": "Mini Butik Ltd", "Pozisyon": "IT", "Kaynak": "LinkedIn", "Şehir": "Ankara",
             "details": "Küçük ekip, startup ortamı", "cover_letter": "", "tailored_cv_path": "", "url": "https://b"},
            {"id": 3, "Durum": STATUS_ANALYZED, "ATS Uyum": "%85", "recommendation": "Başvur",
             "Şirket": "Bilinmeyen Teknoloji", "Pozisyon": "Ağ Uzmanı", "Kaynak": "Kariyer.net", "Şehir": "Ankara",
             "details": "Ağ yönetimi", "cover_letter": "", "tailored_cv_path": "", "url": "https://c"},
        ])
        only_big = campaign.eligible_jobs(df, min_score=65, only_large=True)
        self.assertEqual(list(only_big["Şirket"]), ["Aselsan"])
        no_small = campaign.eligible_jobs(df, min_score=65, only_large=False, exclude_small=True)
        # Büyük şirket öne alınır, küçük elenir
        self.assertEqual(list(no_small["Şirket"]), ["Aselsan", "Bilinmeyen Teknoloji"])
        opps = jobbot.ready_opportunities(df, min_score=75, only_large=True)
        self.assertEqual([o["Şirket"] for o in opps], ["Aselsan"])


if __name__ == "__main__":
    unittest.main()
