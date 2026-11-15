"""Kodla yapılan CV/ilan eşleştirmesinin testleri (LM Studio gerekmez).
Çalıştırma:  venv/bin/python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

from ai_engine.cv_profile import build_profile
from ai_engine.job_matcher import (match, required_years, find_skills, blended_score, recommendation_for,
                                   verify_requirements, rubric_score, drop_profile_requirements)
from ai_engine.brain import _fix_singular

TODAY = date(2026, 11, 10)

CV = """Beceriler
Ağ Yönetimi: Cisco, HP Procurve, VLAN, STP
Sanallaştırma: Proxmox, VMware ESXi, Hyper - V
Deneyim
Sistem Yöneticisi
ÖRNEK A.Ş.
Ankara
Aralık 2023 – Günümüz
• Windows Server (AD, DNS, DHCP) yönettim.
Bilgi İşlem Teknikeri
DİĞER LTD.
Ankara
Eylül 2021 – Haziran 2023
• Son kullanıcı desteği.
Bilgi İşlem Stajyeri
KURUM
Ankara
Temmuz 2021 – Ağustos 2021
Eğitim
Yönetim Bilişim Sistemleri
Anadolu Üniversitesi
Bilgi Güvenliği Teknolojisi (Ön Lisans)
Karabük Üniversitesi
Eylül 2019 – Eylül 2021
Sertifikalar
Labris Firewall Yönetimi
"""


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.p = build_profile(CV, TODAY)

    def test_experience_excludes_internship_and_education(self):
        # Ara 2023–Kas 2026 = 36 ay, Eyl 2021–Haz 2023 = 22 ay; staj ve eğitim sayılmaz
        self.assertEqual(self.p.professional_months, 58)
        self.assertEqual(self.p.professional_years, 4.8)

    def test_education_families(self):
        self.assertEqual(self.p.education_families, {"bilisim_sistemleri", "bilgi_guvenligi"})


class SkillTests(unittest.TestCase):
    def test_spaced_hyphen_and_aliases(self):
        sk = find_skills(CV)
        self.assertTrue({"Cisco", "VMware", "HP/Aruba", "Active Directory"} <= sk)
        self.assertIn("Hyper-V", sk)
        self.assertIn("VMware", sk)

    def test_no_false_positive_from_company_suffix(self):
        self.assertNotIn("SAN", find_skills("Örnek Tic. ve San. A.Ş. sanal sunucu"))
        self.assertIn("SAN", find_skills("SAN ve iSCSI depolama"))

    def test_word_boundaries(self):
        self.assertNotIn("SQL", find_skills("MySQL deneyimi"))
        self.assertNotIn("Java", find_skills("JavaScript geliştirme"))


class RequirementTests(unittest.TestCase):
    def test_required_years(self):
        self.assertEqual(required_years("En az \n5 yıl\n ağ yönetimi"), 5)
        self.assertEqual(required_years("alanlarında 3–5 yıl deneyimli"), 3)
        self.assertEqual(required_years("Minimum 4 years of experience in DevOps"), 4)
        self.assertIsNone(required_years("Ekip çalışmasına yatkın"))

    def test_match_facts(self):
        p = build_profile(CV, TODAY)
        job = ("Bilgisayar Mühendisliği veya Yönetim Bilişim Sistemleri bölümlerinden mezun. En az 5 yıl deneyim. "
               "Cisco, VLAN, BGP, OSPF, Fortinet bilgisi. Tercihen CCNA sertifikası.")
        f = match(job, CV, p)
        self.assertIn("Cisco", f.matched_required)
        self.assertIn("BGP", f.missing_required)
        self.assertIn("CCNA", f.missing_preferred)
        self.assertNotIn("CCNA", f.missing_required)
        self.assertTrue(f.degree_match)
        self.assertFalse(f.experience_ok)  # 4.8 < 5

    def test_hard_degree_mismatch_caps_score(self):
        p = build_profile(CV, TODAY)
        job = "Elektrik ve Elektronik Mühendisliği bölümlerinden mezun. Linux, Cisco, VLAN, DNS bilgisi."
        f = match(job, CV, p)
        self.assertFalse(f.degree_match)
        self.assertFalse(f.degree_flexible)
        score, _ = blended_score(90, f)
        self.assertLessEqual(score, 35)
        self.assertEqual(recommendation_for(score), "Başvurma")

    def test_language_not_counted_in_coverage(self):
        p = build_profile(CV, TODAY)
        cv = CV + "\nYabancı Dil: İngilizce (B2)"
        job = "İyi derecede İngilizce. BGP, OSPF, EIGRP bilgisi."
        f = match(job, cv, p)
        self.assertIn("İngilizce", f.matched_required)  # yine de listelenir
        self.assertEqual(f.skill_coverage, 0.0)  # ama kapsamı şişirmez (1/4 değil 0/3)

    def test_unknown_extra_requirement(self):
        p = build_profile(CV, TODAY)
        f = match("B sınıfı ehliyeti bulunan, Cisco VLAN DNS", CV, p)
        self.assertIn("B sınıfı ehliyet", f.extra_checks)
        self.assertIsNone(f.extra_checks["B sınıfı ehliyet"])  # profile.json yok -> bilinmiyor


class RubricTests(unittest.TestCase):
    def test_fake_evidence_downgraded(self):
        reqs = [
            {"item": "VLAN", "status": "var", "evidence": "VLAN"},               # CV'de var
            {"item": "Kubernetes", "status": "var", "evidence": "Kubernetes"},   # uydurma
            {"item": "Liderlik", "status": "var", "evidence": ""},               # kanıtsız
        ]
        fixed, down = verify_requirements(reqs, CV)
        self.assertEqual([r["status"] for r in fixed], ["var", "kısmen", "kısmen"])
        self.assertEqual(down, ["Kubernetes", "Liderlik"])

    def test_profile_requirements_dropped(self):
        reqs = [{"item": "B sınıfı ehliyet", "status": "yok", "evidence": ""},
                {"item": "Yurt içi / yurt dışı seyahat", "status": "yok", "evidence": ""},
                {"item": "Cisco switch yönetimi", "status": "var", "evidence": "Cisco"}]
        kept, dropped = drop_profile_requirements(reqs)
        self.assertEqual([r["item"] for r in kept], ["Cisco switch yönetimi"])
        self.assertEqual(len(dropped), 2)

    def test_rubric_spreads_scores(self):
        def reqs(*st):
            return [{"item": str(i), "status": x, "evidence": ""} for i, x in enumerate(st)]
        same_role_full = rubric_score(reqs("var", "var", "var", "kısmen"), 4)
        near_role_half = rubric_score(reqs("var", "kısmen", "yok", "yok"), 3)
        other_job = rubric_score(reqs("yok", "yok", "kısmen", "yok"), 0)
        self.assertGreater(same_role_full, 85)
        self.assertTrue(45 <= near_role_half <= 65)
        self.assertLess(other_job, 10)
        self.assertEqual(rubric_score([], 2), 50)


class TextFixTests(unittest.TestCase):
    def test_singular(self):
        self.assertEqual(_fix_singular("Başvurumuzu değerlendirmenizi rica ederiz."),
                         "Başvurumu değerlendirmenizi rica ederim.")


if __name__ == "__main__":
    unittest.main()
