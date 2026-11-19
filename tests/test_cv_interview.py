"""CV Koçu (soru → cevap → denetimli güncelleme) ve CV şablonları. Model gerektirmez."""
import unittest
from unittest import mock

from ai_engine import cv_interview as ci
from ai_engine import cv_studio as cs


def sample():
    p = cs.empty_profile()
    p.update({
        "name": "Ayşe Yılmaz", "headline": "Sistem Yöneticisi", "email": "a@b.com", "phone": "0532 000 00 00",
        "summary": "Kısa özet.",
        "skills": [{"group": "Sistem", "items": ["Windows Server", "Linux"]}],
        "experience": [
            {"title": "Sistem Yöneticisi", "company": "Örnek A.Ş.", "city": "Ankara", "dates": "2022 – Günümüz",
             "bullets": [{"text": "Windows Server ve Linux sunucuları yönettim.", "user": False},
                         {"text": "Mware ortamında sanal makineleri kurdum.", "user": False}]},
            {"title": "Teknik Destek", "company": "Deneme Ltd.", "city": "", "dates": "2020 – 2022",
             "bullets": [{"text": "Kullanıcılara destek verdim.", "user": False}]},
        ],
        "education": ["Bilgisayar Programcılığı · Ankara Üniversitesi"],
    })
    return p


ORIGINAL = "Ayşe Yılmaz Sistem Yöneticisi Windows Server Linux Mware Kullanıcılara destek verdim."


class RuleQuestionTests(unittest.TestCase):
    def test_finds_gaps(self):
        qs = {q["key"]: q for q in ci.rule_questions(sample(), ORIGINAL)}
        self.assertIn("typo:Mware", qs)
        self.assertEqual(qs["typo:Mware"]["kind"], "yesno")
        self.assertIn("num:0", qs)          # 1. işte sayı yok
        self.assertIn("tasks:1", qs)        # 2. işte tek madde var
        self.assertIn("languages", qs)
        self.assertIn("summary", qs)
        self.assertIn("skills", qs)
        self.assertNotIn("headline", qs)    # başlık dolu

    def test_build_skips_already_asked(self):
        p = sample()
        p["qa_log"] = [{"key": "languages", "question": "dil?", "answer": "İngilizce B1"},
                       {"key": "typo:Mware", "question": "?", "answer": "Hayır"}]
        qs, err = ci.build_questions(p, ORIGINAL, use_ai=False)
        keys = {q["key"] for q in qs}
        self.assertIsNone(err)
        self.assertNotIn("languages", keys)
        self.assertNotIn("typo:Mware", keys)
        self.assertLessEqual(len(qs), ci.MAX_QUESTIONS)

    def test_ai_failure_falls_back_to_rules(self):
        with mock.patch.object(ci, "ai_questions", side_effect=RuntimeError("LM Studio kapalı")):
            qs, err = ci.build_questions(sample(), ORIGINAL)
        self.assertIn("LM Studio", err)
        self.assertTrue(qs)


class ProposeTests(unittest.TestCase):
    def q(self, key, section, answer, **kw):
        return {"key": key, "section": section, "question": key, "kind": kw.pop("kind", "text"), "answer": answer, **kw}

    def test_non_answers_are_skipped(self):
        qa = [self.q("num:0", "exp:0", "bilmiyorum"), self.q("skills", "skills", "yok"), self.q("extras", "extras", " ")]
        out = ci.propose_edits(sample(), ORIGINAL, qa, use_ai=False)
        self.assertEqual(out["accepted"], [])

    def test_fallback_uses_users_words(self):
        qa = [self.q("num:0", "exp:0", "yaklaşık 300 kullanıcıya destek verdim"),
              self.q("skills", "skills", "Zabbix, linux, Veeam"),
              self.q("languages", "languages", "İngilizce – orta (B1)"),
              self.q("typo:Mware", "typo", "Evet", kind="yesno", wrong="Mware", fix="VMware")]
        out = ci.propose_edits(sample(), ORIGINAL, qa, use_ai=False)
        by = {e["where"]: e for e in out["accepted"]}
        self.assertEqual(by["exp:0:+"]["new"], "Yaklaşık 300 kullanıcıya destek verdim.")
        self.assertEqual(by["skills:+"]["new"], "Zabbix, Veeam")   # 'linux' zaten var
        self.assertEqual(by["languages"]["new"], "İngilizce – orta (B1)")
        self.assertEqual(by["typo"]["new"], "VMware")

    def test_typo_no_means_no_change(self):
        qa = [self.q("typo:Mware", "typo", "Hayır", kind="yesno", wrong="Mware", fix="VMware")]
        self.assertEqual(ci.propose_edits(sample(), ORIGINAL, qa, use_ai=False)["accepted"], [])

    def test_ai_fabrication_is_rejected_and_answer_kept(self):
        qa = [self.q("num:0", "exp:0", "300 kullanıcıya destek verdim")]
        fake = [{"where": "exp:0:+", "text": "Kubernetes ile 300 kullanıcılı 5000 podluk altyapı kurdum.", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, qa)
        self.assertEqual(len(out["rejected"]), 1)          # Kubernetes ve 5000 uydurma
        self.assertEqual([e["new"] for e in out["accepted"]], ["300 kullanıcıya destek verdim."])  # cevap kaybolmaz

    def test_info_losing_rewrite_becomes_new_bullet(self):
        qa = [self.q("ai:x", "exp:0", "Zabbix ile arızayı 25 dakikada çözdüm")]
        fake = [{"where": "exp:0:0", "text": "Zabbix ile kritik arızayı 25 dakikada çözdüm.", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, qa)
        self.assertEqual([e["where"] for e in out["accepted"]], ["exp:0:+"])   # Windows/Linux maddesi silinmez
        self.assertEqual(out["accepted"][0]["new"], "Zabbix ile kritik arızayı 25 dakikada çözdüm.")

    def test_good_ai_rewrite_of_bullet_is_accepted(self):
        qa = [self.q("num:1", "exp:1", "yaklaşık 200 kullanıcı")]
        fake = [{"where": "exp:1:0", "text": "Yaklaşık 200 kullanıcıya teknik destek verdim.", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, qa)
        self.assertEqual(out["accepted"][0]["where"], "exp:1:0")
        self.assertEqual(out["accepted"][0]["old"], "Kullanıcılara destek verdim.")

    def test_ai_error_reported_and_fallback_used(self):
        qa = [self.q("extras", "extras", "B sınıfı ehliyet; askerlik yapıldı")]
        with mock.patch.object(ci, "_ai_edits", side_effect=RuntimeError("bağlantı yok")):
            out = ci.propose_edits(sample(), ORIGINAL, qa)
        self.assertIn("bağlantı", out["ai_error"])
        self.assertEqual([e["new"] for e in out["accepted"]], ["B sınıfı ehliyet", "askerlik yapıldı"])


class ApplyTests(unittest.TestCase):
    def test_apply_and_log(self):
        p = sample()
        edits = [{"where": "typo", "old": "Mware", "new": "VMware"},
                 {"where": "exp:0:+", "old": "", "new": "300 kullanıcıya destek verdim."},
                 {"where": "skills:+", "old": "", "new": "Zabbix, Veeam"},
                 {"where": "languages", "old": "", "new": "İngilizce B1"},
                 {"where": "extras:+", "old": "", "new": "B sınıfı ehliyet"}]
        qa = [{"key": "num:0", "section": "exp:0", "question": "Sayı?", "answer": "300 kullanıcı"},
              {"key": "summary", "section": "summary", "question": "Özet?", "answer": ""}]
        ci.apply_edits(p, edits, qa)
        self.assertEqual(p["experience"][0]["bullets"][1]["text"], "VMware ortamında sanal makineleri kurdum.")
        self.assertEqual(p["experience"][0]["bullets"][-1], {"text": "300 kullanıcıya destek verdim.", "user": True})
        self.assertIn({"group": "Diğer Araçlar", "items": ["Zabbix", "Veeam"]}, p["skills"])
        self.assertEqual(p["languages"], "İngilizce B1")
        self.assertIn("B sınıfı ehliyet", p["extras"])
        self.assertEqual(ci.asked_keys(p), {"num:0", "summary"})   # atlanan soru da tekrar sorulmaz
        self.assertIn("300 kullanıcı", cs.source_text(p, ORIGINAL))  # cevaplar artık kaynak sayılır
        ci.apply_edits(p, [], qa)
        self.assertEqual(len(p["qa_log"]), 2)                          # aynı soru iki kez yazılmaz

    def test_vmware_not_double_fixed(self):
        p = sample()
        p["experience"][0]["bullets"][0]["text"] = "VMware ve Mware"
        ci.apply_edits(p, [{"where": "typo", "old": "Mware", "new": "VMware"}])
        self.assertEqual(p["experience"][0]["bullets"][0]["text"], "VMware ve VMware")


class QuestionQualityTests(unittest.TestCase):
    def test_bad_ai_questions_filtered(self):
        bad = ["Mezun olmadan önce hangi projelerde liderlik edeceksiniz?",
               "Mware yazım hatası dışında en büyük sorununuz neydi?",
               "SIEM becerilerinizi iddia ediyorsunuz, hangi aracı kullandınız?",
               "Kesintiyi nasıl buldunuz? Kaç dakikada çözdünüz?", "Ne?"]
        for q in bad:
            self.assertTrue(ci.question_problems(q), q)
        self.assertEqual(ci.question_problems("SIEM tarafında hangi aracı kullandınız (Wazuh, Graylog...)?"), [])

    def test_ai_questions_filtered_inside_pipeline(self):
        fake = {"questions": [
            {"section": "exp:0", "question": "Hangi projelerde liderlik edeceksiniz?", "why": "x", "example": ""},
            {"section": "exp:9", "question": "Kaç sunucuyu tek başınıza yönettiniz?", "why": "kapsam", "example": "40"},
        ]}
        with mock.patch("ai_engine.brain._chat_json", return_value=fake):
            qs = ci.ai_questions(sample(), ORIGINAL)
        self.assertEqual([q["question"] for q in qs], ["Kaç sunucuyu tek başınıza yönettiniz?"])
        self.assertEqual(qs[0]["section"], "extras")   # olmayan deneyim numarası güvenli bölüme alınır

    def test_new_rule_questions(self):
        p = sample()
        p["languages"] = "İngilizce"
        p["certificates"] = ["CCNA · Cisco", "Labris Firewall · 2024"]
        p["links"] = []
        with mock.patch.object(ci, "_field", return_value="it"):
            keys = {q["key"] for q in ci.rule_questions(p, ORIGINAL)}
        self.assertTrue({"langlevel", "certyear:0", "linkedin", "github", "extras"} <= keys)
        self.assertNotIn("certyear:1", keys)
        with mock.patch.object(ci, "_field", return_value="ik"):   # BT dışı kullanıcıya GitHub sorulmaz
            self.assertNotIn("github", {q["key"] for q in ci.rule_questions(p, ORIGINAL)})

    def test_language_level_cert_year_links_edits(self):
        p = sample()
        p["languages"], p["certificates"] = "İngilizce", ["CCNA · Cisco"]
        qa = [{"key": "langlevel", "section": "languages", "question": "?", "answer": "B1 orta"},
              {"key": "certyear:0", "section": "cert:0", "question": "?", "answer": "2023"},
              {"key": "github", "section": "links", "question": "?", "answer": "github.com/ayse"}]
        out = ci.propose_edits(p, ORIGINAL, qa, use_ai=False)
        by = {e["where"]: e["new"] for e in out["accepted"]}
        self.assertEqual(by, {"languages": "İngilizce – B1 orta", "certificates:0": "CCNA · Cisco · 2023",
                              "links:+": "github.com/ayse"})
        ci.apply_edits(p, out["accepted"], qa)
        self.assertEqual(p["certificates"], ["CCNA · Cisco · 2023"])
        self.assertEqual(p["links"], ["github.com/ayse"])


class ReviewRegressionTests(unittest.TestCase):
    """2026-11-17 bağımsız incelemede bulunan hatalar."""
    def q(self, key, section, answer):
        return {"key": key, "section": section, "question": key, "kind": "text", "answer": answer}

    def test_ai_cannot_bypass_validation_with_typo_target(self):
        fake = [{"where": "typo", "text": "Kubernetes ve AWS uzmanı, 15 yıl deneyim", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, [self.q("summary", "summary", "ağ yönetimi")])
        self.assertFalse(any(e["where"] == "typo" for e in out["accepted"]))
        p = sample()
        skipped = ci.apply_edits(p, [{"where": "typo", "old": "", "new": "Kubernetes"}])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(p["summary"], "Kısa özet.")

    def test_typo_fix_is_literal_and_covers_all_fields(self):
        p = sample()
        p["headline"], p["extras"] = "Mware uzmanı", ["Mware kursu"]
        ci.apply_edits(p, [{"where": "typo", "old": "Mware", "new": "VMware"}])
        self.assertEqual(p["headline"], "VMware uzmanı")
        self.assertEqual(p["extras"], ["VMware kursu"])

    def test_stale_target_is_skipped_not_overwritten(self):
        p = sample()
        p["certificates"] = ["CCNA · Cisco", "Fortinet NSE 4"]
        edit = {"where": "certificates:0", "old": "CCNA · Cisco", "new": "CCNA · Cisco · 2023"}
        del p["certificates"][0]                       # kullanıcı bu arada CCNA'yı sildi
        skipped = ci.apply_edits(p, [edit])
        self.assertEqual(p["certificates"], ["Fortinet NSE 4"])
        self.assertEqual(skipped, [edit])
        p["experience"] = []
        self.assertEqual(len(ci.apply_edits(p, [{"where": "exp:0:+", "old": "", "new": "X yaptım."}])), 1)

    def test_language_and_certificate_info_not_lost(self):
        p = sample()
        p["languages"] = "İngilizce – B2, Almanca – A2"
        p["certificates"] = ["CCNA · Cisco", "Fortinet NSE 4"]
        self.assertEqual(ci.merge_language(p["languages"], "İngilizce C1"), "İngilizce C1, Almanca – A2")
        fake = [{"where": "languages", "text": "İngilizce", "answer": 0},
                {"where": "certificates:1", "text": "Fortinet", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(p, ORIGINAL, [self.q("x", "extras", "bir şey")])
        self.assertFalse([e for e in out["accepted"] if e["where"] in ("languages", "certificates:1")])

    def test_two_edits_on_same_bullet_both_survive(self):
        fake = [{"where": "exp:0:0", "text": "Windows Server ve Linux ile 40 sunucuyu yönettim.", "answer": 0},
                {"where": "exp:0:0", "text": "Windows Server ve Linux sunucularını Veeam ile yedekleyerek yönettim.", "answer": 1}]
        qa = [self.q("a", "exp:0", "40 sunucu"), self.q("b", "exp:0", "Veeam ile yedekleme")]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, qa)
        p = sample()
        ci.apply_edits(p, out["accepted"], qa)
        texts = " ".join(b["text"] for b in p["experience"][0]["bullets"])
        self.assertIn("40 sunucu", texts)
        self.assertIn("Veeam", texts)

    def test_out_of_range_ai_edit_does_not_drop_batch(self):
        fake = [{"where": "exp:7:+", "text": "Bir şey yaptım.", "answer": 0},
                {"where": "skills:+", "text": "Zabbix", "answer": 0}]
        with mock.patch.object(ci, "_ai_edits", return_value=fake):
            out = ci.propose_edits(sample(), ORIGINAL, [self.q("skills", "skills", "Zabbix")])
        self.assertIsNone(out["ai_error"])
        self.assertEqual([e["new"] for e in out["accepted"]], ["Zabbix"])


class AuditTests(unittest.TestCase):
    def failing_msgs(self, p, **kw):
        from ai_engine import cv_audit
        return " | ".join(c["msg"] for c in cv_audit.failing(cv_audit.audit(p, **kw)))

    def test_detects_gaps(self):
        msgs = self.failing_msgs(sample())
        for part in ("LinkedIn", "Yabancı dil", "ölçülebilir", "Yazım hatası var", "Askerlik", "Sürücü belgesi"):
            self.assertIn(part, msgs)

    def test_personal_data_and_order(self):
        p = sample()
        p["extras"] = ["Doğum tarihi: 01.01.1995", "TC: 12345678901"]
        p["experience"].reverse()   # eskiden yeniye: yanlış
        msgs = self.failing_msgs(p)
        self.assertIn("doğum tarihi", msgs)
        self.assertIn("TC kimlik", msgs)
        self.assertIn("yeniden eskiye", msgs)

    def test_job_keywords(self):
        msgs = self.failing_msgs(sample(), job_text="Aranan: Cisco, Fortinet ve Linux bilgisi")
        self.assertIn("Fortinet", msgs)
        self.assertNotIn("Linux,", msgs)

    def test_score_improves_when_fixed(self):
        from ai_engine import cv_audit
        p = sample()
        before = cv_audit.score(cv_audit.audit(p))
        p.update(languages="İngilizce – B1", links=["linkedin.com/in/ayse"], extras=["B sınıfı ehliyet"])
        self.assertGreater(cv_audit.score(cv_audit.audit(p)), before)
        self.assertLessEqual(cv_audit.score(cv_audit.audit(p)), 100)


class TemplateTests(unittest.TestCase):
    def test_at_least_five_templates_render(self):
        self.assertGreaterEqual(len(cs.TEMPLATE_INFO), 5)
        p = sample()
        for t, info in cs.TEMPLATE_INFO.items():
            doc = cs.render_html(p, t, "data:image/png;base64,AAAA" if info["photo"] else None, "#123456")
            self.assertIn("Ayşe Yılmaz", doc, t)
            self.assertIn("Windows Server ve Linux sunucuları yönettim.", doc, t)
            self.assertIn("Bilgisayar Programcılığı", doc, t)
            self.assertEqual(set(cs.TEMPLATE_INFO[t]) >= {"label", "desc", "best", "photo", "ats"}, True)

    def test_html_is_escaped(self):
        p = sample()
        p["summary"] = "<script>alert(1)</script>"
        for t in cs.TEMPLATE_INFO:
            self.assertNotIn("<script>alert", cs.render_html(p, t), t)

    def test_highlights_only_existing_numbered_bullets(self):
        p = sample()
        p["experience"][1]["bullets"].append({"text": "450 kullanıcıya ve 12 şubeye destek verdim.", "user": False})
        self.assertEqual(cs.highlights(p), ["450 kullanıcıya ve 12 şubeye destek verdim."])

    def test_old_profiles_get_defaults(self):
        p = {**cs.empty_profile(), **{"name": "X"}}
        self.assertEqual(p["template"], "modern")
        self.assertEqual(p["qa_log"], [])


if __name__ == "__main__":
    unittest.main()
