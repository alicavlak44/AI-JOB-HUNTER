"""İlana özel CV üreticisinin uydurma denetimi testleri (LM Studio gerekmez).
Çalıştırma:  venv/bin/python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from ai_engine.cv_builder import (parse_cv, check_text, apply_suggestion, write_docx, docx_text,
                                  tr_title, tr_upper)

CV = """Kişisel Bilgiler
ornek@example.com
Ankara
Beceriler
Ağ Yönetimi: Cisco, VLAN, STP,
TCP/IP
Sistem Yönetimi: Windows Server (AD, DNS), Linux
Diller
İngilizce
AYŞE YILMAZ
Sistem Yöneticisi
Özet
3 yerleşkede 1.200 kullanıcılı ağları yöneten sistem yöneticisi.
Deneyim
Sistem Yöneticisi
ÖRNEK A.Ş.
Ankara
Ocak 2022 – Günümüz
• 1.200 kullanıcı için Cisco switch VLAN ve STP yapılandırmalarını
yönettim.
• Windows Server üzerinde AD ve DNS servislerini kurdum.
• Linux sunucuların yedekleme süreçlerini yürüttüm.
Bilgi İşlem Stajyeri
DENEME KURUMU
Ankara
Temmuz 2021 – Ağustos 2021
• Son kullanıcı desteği verdim.
Eğitim
Bilgisayar Programcılığı
Örnek Üniversitesi
2021
Sertifikalar
Cisco Ağ Temelleri
Örnek Akademi
Tarih
"""


def empty():
    return {"headline": "", "summary": "", "skill_group_order": [], "skill_priority": [], "experience": []}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.cv = parse_cv(CV)

    def test_header_and_sections(self):
        self.assertEqual(self.cv.name, "AYŞE YILMAZ")
        self.assertEqual(self.cv.headline, "Sistem Yöneticisi")
        self.assertEqual(self.cv.contact, ["ornek@example.com", "Ankara"])
        self.assertEqual(self.cv.languages, "İngilizce")

    def test_skill_groups_do_not_bleed(self):
        self.assertEqual(self.cv.skill_groups, [
            ("Ağ Yönetimi", ["Cisco", "VLAN", "STP", "TCP/IP"]),
            ("Sistem Yönetimi", ["Windows Server (AD, DNS)", "Linux"]),
        ])

    def test_experience_and_wrapped_bullets(self):
        e1, e2 = self.cv.experience
        self.assertEqual((e1.title, e1.company, e1.city), ("Sistem Yöneticisi", "ÖRNEK A.Ş.", "Ankara"))
        self.assertEqual(len(e1.bullets), 3)
        self.assertTrue(e1.bullets[0].text.endswith("yapılandırmalarını yönettim."))
        self.assertEqual(e2.title, "Bilgi İşlem Stajyeri")

    def test_placeholder_date_is_flagged(self):
        self.assertEqual(self.cv.certificates, [["Cisco Ağ Temelleri", "Örnek Akademi"]])
        self.assertTrue(any("Tarih" in w for w in self.cv.warnings))


class FabricationTests(unittest.TestCase):
    def test_check_text(self):
        src = "1.200 kullanıcı için Cisco switch VLAN yapılandırmalarını yönettim."
        self.assertEqual(check_text("Cisco ile 1.200 kullanıcılı ağda VLAN yönetimi.", src), [])
        self.assertTrue(check_text("Cisco ve Kubernetes ile VLAN yönetimi.", src))   # yeni beceri
        self.assertTrue(check_text("5.000 kullanıcı için Cisco VLAN yönetimi.", src))  # yeni sayı
        self.assertTrue(check_text("3 yerleşkede 1.200 kullanıcı; 3 yıl deneyim.", "3 yerleşke 1.200", cv_years=2.8))
        self.assertTrue(check_text("Python ile ağ otomasyonu yaptım.", "Python, Bash"))           # yeni iddia
        self.assertEqual(check_text("Python ile betik yazdım.", "Python, Bash"), [])

    def test_suggestion_is_validated(self):
        cv = parse_cv(CV)
        data = empty()
        data.update(
            summary="10 yıllık deneyimli, AWS uzmanı sistem yöneticisi.",           # uydurma → red
            skill_group_order=["Sistem Yönetimi", "Ağ Yönetimi"],
            skill_priority=["Linux", "STP"],
            experience=[{"id": "E1", "bullets": [
                {"source": "E1.B3", "text": "Linux sunucularda yedekleme süreçlerini yönettim."},  # kabul
                {"source": "E1.B1", "text": "1.200 kullanıcı için Cisco, VLAN, STP ve Kubernetes yönettim."},  # red
                {"source": "E9.B1", "text": "Uydurma madde."},                                  # kaynak yok
                {"source": "E1.B2", "text": "Windows Server üzerinde AD ve DNS kurdum."},             # kabul
            ]}],
        )
        out, rep = apply_suggestion(cv, data, CV, cv_years=2.8)
        self.assertEqual(out.summary, cv.summary)
        e1 = out.experience[0]
        self.assertEqual([b.id for b in e1.bullets], ["E1.B3", "E1.B1", "E1.B2"])  # sıra değişti, hiçbiri silinmedi
        self.assertEqual(e1.bullets[0].text, "Linux sunucularda yedekleme süreçlerini yönettim.")
        self.assertEqual(e1.bullets[1].text, cv.experience[0].bullets[0].text)    # red → orijinal
        self.assertEqual(len(rep["rejected"]), 3)
        self.assertEqual([g[0] for g in out.skill_groups], ["Sistem Yönetimi", "Ağ Yönetimi"])
        self.assertEqual(out.skill_groups[1][1][0], "STP")
        self.assertEqual(sorted(sum((g[1] for g in out.skill_groups), [])),
                         sorted(sum((g[1] for g in cv.skill_groups), [])))  # beceri eklenmedi/silinmedi

    def test_wrong_entry_id_still_applied(self):
        cv = parse_cv(CV)
        data = empty()
        data["experience"] = [{"id": "E1.B1", "bullets": [
            {"source": "[E1.B3]", "text": "Linux sunucularda yedekleme süreçlerini yönettim."}]}]
        out, rep = apply_suggestion(cv, data, CV, cv_years=2.8)
        self.assertEqual(out.experience[0].bullets[0].text, "Linux sunucularda yedekleme süreçlerini yönettim.")

    def test_numbers_must_be_kept(self):
        cv = parse_cv(CV)
        data = empty()
        data["experience"] = [{"id": "E1", "bullets": [
            {"source": "E1.B1", "text": "Cisco switch VLAN ve STP yapılandırmalarını yönettim."}]}]  # 1.200 silinmiş
        out, rep = apply_suggestion(cv, data, CV, cv_years=2.8)
        self.assertEqual(out.experience[0].bullets[0].text, cv.experience[0].bullets[0].text)
        self.assertIn("sayı silindi", rep["rejected"][0]["why"][0])

    def test_docx_passes_final_check(self):
        out, _ = apply_suggestion(parse_cv(CV), empty(), CV, cv_years=2.8)
        with tempfile.TemporaryDirectory() as d:
            path = write_docx(out, os.path.join(d, "cv.docx"))
            text = docx_text(path)
        self.assertEqual(check_text(text, CV), [])
        self.assertIn("Ayşe Yılmaz", text)
        self.assertIn("EĞİTİM", text)


class CasingTests(unittest.TestCase):
    def test_turkish_case(self):
        self.assertEqual(tr_title("ALİ IŞIK"), "Ali Işık")
        self.assertEqual(tr_upper("Sertifikalar ve Eğitim"), "SERTİFİKALAR VE EĞİTİM")


class CVStudioInfoLossTests(unittest.TestCase):
    """2026-11-15 canlı test: yapay zeka 'iyileştirmesi' teknoloji ve görevleri siliyordu."""

    def test_rejects_lost_tech_numbers_tasks(self):
        from ai_engine.cv_studio import info_loss
        self.assertTrue(info_loss("Windows Server (AD, GPO, DNS, DHCP, File Server) ve Linux/Nginx sistemlerini kurup yönettim.",
                                  "Windows Server (AD, DNS, DHCP) ve Linux sistemlerini kurup yöneterek altyapı sürekliliğini sağladım."))
        self.assertTrue(info_loss("Linux tabanlı son kullanıcı destek masasını sıfırdan oluşturarak BT operasyonlarını ve arıza takip süreçlerini merkezileştirdim.",
                                  "Linux tabanlı son kullanıcı destek masasını sıfırdan oluşturarak BT operasyonlarını merkezileştirdim."))
        self.assertTrue(info_loss("15 sunucuyu sanallaştırdım.", "Sunucuları sanallaştırdım."))

    def test_accepts_good_rewrites(self):
        from ai_engine.cv_studio import info_loss
        self.assertEqual(info_loss("Sunucuları yönettim ve yedekledim.",
                                   "Kurumsal sunucuların yönetimini ve düzenli yedeklemesini üstlendim."), [])


if __name__ == "__main__":
    unittest.main()
