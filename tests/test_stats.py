"""İstatistik hesaplarının testleri (veritabanı gerekmez).
Çalıştırma:  venv/bin/python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

import pandas as pd

from app.settings import STATUS_APPLIED_VERIFIED, STATUS_APPLY_UNVERIFIED, STATUS_NEW, STATUS_ANALYZED
from database.stats import parse_score, summary, daily, funnel, score_distribution, sentence

TODAY = date(2026, 11, 10)

DF = pd.DataFrame([
    # bugün bulunup analiz edilen, özel CV'li, doğrulanmış başvuru
    dict(created_at="2026-11-10 09:00:00", analyzed_at="2026-11-10 10:00:00", cv_created_at="2026-11-10 10:05:00",
         applied_at="2026-11-10 11:00:00", **{"ATS Uyum": "%72", "Durum": STATUS_APPLIED_VERIFIED}, recommendation="Başvur"),
    # bugün bulundu, analiz yok
    dict(created_at="2026-11-10 09:30:00", analyzed_at=None, cv_created_at=None, applied_at=None,
         **{"ATS Uyum": "-", "Durum": STATUS_NEW}, recommendation=None),
    # 3 gün önce bulunup analiz edildi, başvuru doğrulanamadı
    dict(created_at="2026-11-07 12:00:00", analyzed_at="2026-11-08 12:00:00", cv_created_at=None, applied_at=None,
         **{"ATS Uyum": "%45", "Durum": STATUS_APPLY_UNVERIFIED}, recommendation="Değerlendir"),
    # 10 gün önce (önceki hafta), eski biçimli puan
    dict(created_at="2026-10-31 12:00:00", analyzed_at="2026-10-31 13:00:00", cv_created_at=None, applied_at=None,
         **{"ATS Uyum": "%15  \n(Altın kelimeler...)", "Durum": STATUS_ANALYZED}, recommendation="Başvurma"),
])


class StatsTests(unittest.TestCase):
    def test_parse_score(self):
        self.assertEqual(parse_score("%62"), 62)
        self.assertEqual(parse_score("%87  \n(Altın ke"), 87)
        self.assertIsNone(parse_score("-"))
        self.assertIsNone(parse_score(None))

    def test_summary_periods(self):
        s = summary(DF, TODAY)
        self.assertEqual(s["today"], {"Bulunan ilan": 2, "Analiz edilen": 1, "Özel CV": 1, "Başvuru (doğrulanmış)": 1})
        self.assertEqual(s["week"]["Bulunan ilan"], 3)
        self.assertEqual(s["week"]["Analiz edilen"], 2)
        self.assertEqual(s["prev_week"]["Bulunan ilan"], 1)

    def test_daily(self):
        d = daily(DF, TODAY, days=14)
        self.assertEqual(len(d), 14)
        self.assertEqual(d.index[-1], pd.Timestamp("2026-11-10"))
        self.assertTrue(d.index.is_monotonic_increasing)
        self.assertEqual(d.loc[pd.Timestamp("2026-11-10"), "Bulunan ilan"], 2)
        self.assertEqual(d.loc[pd.Timestamp("2026-11-08"), "Analiz edilen"], 1)
        self.assertEqual(int(d["Bulunan ilan"].sum()), 4)

    def test_funnel(self):
        f = funnel(DF)["Adet"].tolist()
        self.assertEqual(f, [4, 3, 1, 1, 2, 1])

    def test_score_distribution(self):
        self.assertEqual(score_distribution(DF)["İlan"].tolist(), [1, 1, 1])

    def test_sentence(self):
        self.assertEqual(sentence(summary(DF, TODAY)["today"], "Bugün"),
                         "Bugün 2 ilan bulundu, 1 analiz yapıldı, 1 özel CV üretildi, 1 başvuru doğrulandı.")

    def test_all_empty_column(self):  # hiç başvuru yokken applied_at tamamen boş
        df = DF.copy()
        df["applied_at"] = None
        self.assertEqual(summary(df, TODAY)["today"]["Başvuru (doğrulanmış)"], 0)
        self.assertEqual(int(daily(df, TODAY)["Başvuru (doğrulanmış)"].sum()), 0)

    def test_empty(self):
        empty = pd.DataFrame(columns=list(DF.columns))
        self.assertEqual(summary(empty, TODAY)["today"]["Bulunan ilan"], 0)
        self.assertEqual(funnel(empty)["Adet"].sum(), 0)


if __name__ == "__main__":
    unittest.main()
