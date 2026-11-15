"""İlan toplama yardımcılarının testleri (internet gerekmez).
Çalıştırma:  venv/bin/python -m unittest discover -s tests -v
"""
import unittest

from browser.scraper import is_relevant, tr_lower, stats_message, new_stats
from browser.automator import kariyernet_search_url


class RelevanceTests(unittest.TestCase):
    def test_it_titles_kept(self):
        for t in ["Bilgi İşlem Uzmanı", "IT Uzmanı", "Network Kıdemli Uzmanı", "Sistem Mühendisi",
                  "DevOps Engineer", "Bilgi Teknolojileri / IT Uzmanı", "Yazılım Destek Uzmanı", "Web Developer"]:
            self.assertTrue(is_relevant(t, "Bilgi İşlem Uzmanı"), t)

    def test_unrelated_uzman_titles_dropped(self):
        # Kariyer.net "Bilgi İşlem Uzmanı" aramasına gerçekten dönen alakasız ilanlar
        for t in ["Dış Ticaret Uzmanı", "Tazminat İşlemleri Kıdemli Uzmanı", "Finans Uzmanı",
                  "Bütçe ve Raporlama Uzmanı", "İş Sağlığı ve Güvenliği Uzmanı", "Dağıtım Sorumlusu"]:
            self.assertFalse(is_relevant(t, "Bilgi İşlem Uzmanı"), t)

    def test_keyword_core_phrase(self):
        self.assertTrue(is_relevant("Kurumsal Bilgi Güvenliği Uzmanı", "Bilgi Güvenliği Mühendisi"))

    def test_turkish_lower(self):
        self.assertEqual(tr_lower("BİLGİ İŞLEM"), "bilgi işlem")
        self.assertEqual(tr_lower("IŞIK"), "ışık")


class KariyerUrlTests(unittest.TestCase):
    def test_city_is_a_filter_not_keyword(self):
        self.assertEqual(kariyernet_search_url("Bilgi İşlem Uzmanı", "Ankara"),
                         "https://www.kariyer.net/is-ilanlari/ankara?kw=bilgi%20i%C5%9Flem%20uzman%C4%B1")
        self.assertTrue(kariyernet_search_url("IT", "İstanbul").startswith("https://www.kariyer.net/is-ilanlari/istanbul?"))
        self.assertTrue(kariyernet_search_url("IT", "").startswith("https://www.kariyer.net/is-ilanlari?kw="))


class MessageTests(unittest.TestCase):
    def test_messages(self):
        st = new_stats()
        self.assertIn("hiç ilan bulunamadı", stats_message("LinkedIn", st))
        st.update(found=25, added=0, duplicate=20, irrelevant=5)
        msg = stats_message("LinkedIn", st)
        self.assertIn("20 tanesi zaten listede", msg)
        self.assertIn("5 alakasız ilan elendi", msg)
        st["error"] = "LinkedIn 429 hatası döndü"
        self.assertTrue(stats_message("LinkedIn", st).startswith("❌"))



class LiveFindingsTests(unittest.TestCase):
    """2026-11-15 canlı testte yanlışlıkla elenen BT ilanları."""

    def test_it_titles_not_dropped(self):
        from browser.scraper import filter_title, new_stats
        for t in ("Kubernetes Administrator", "Presales Systems Engineer, Ankara", "Atlassian Çözüm Uzmanı"):
            self.assertTrue(filter_title(t, "Sistem Yöneticisi", new_stats()), t)

    def test_real_sales_still_dropped(self):
        from browser.scraper import filter_title, new_stats
        self.assertFalse(filter_title("Sales Manager", "Sistem Yöneticisi", new_stats()))
        self.assertFalse(filter_title("Satış Temsilcisi", "Sistem Yöneticisi", new_stats()))


if __name__ == "__main__":
    unittest.main()
