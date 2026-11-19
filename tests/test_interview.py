"""Mülakat Provası: soru planı, değerlendirme, karne, ses dönüştürme (model / mikrofon gerektirmez)."""
import io
import tempfile
import unittest
import wave
from unittest import mock

import numpy as np

from ai_engine import interview as iv
from ai_engine import voice

PROFILE = {"name": "Ayşe Yılmaz", "headline": "Sistem Yöneticisi", "summary": "Kurumsal ağ yönetimi.",
           "skills": [{"group": "Ağ", "items": ["Cisco", "VLAN"]}],
           "experience": [{"title": "Sistem Yöneticisi", "company": "X A.Ş.", "dates": "2022 - 2024",
                           "bullets": [{"text": "300 kullanıcılı ağı yönettim.", "user": False}]}]}
CV = "Ayşe Yılmaz Sistem Yöneticisi Cisco VLAN 300 kullanıcılı ağı yönettim."


class PlanTests(unittest.TestCase):
    def test_structure_without_ai(self):
        qs, err = iv.plan_interview(PROFILE, "it", n_tech=3, n_beh=2, use_ai=False)
        self.assertIsNone(err)
        self.assertEqual([q["stage"] for q in qs],
                         ["intro", "motivation", "technical", "technical", "technical", "behavioral", "behavioral", "closing"])
        self.assertEqual([q["id"] for q in qs][:2], ["Q1", "Q2"])
        self.assertTrue(all(q["question"].endswith("?") and q["expects"] for q in qs))

    def test_field_banks(self):
        it = {q["question"] for q in iv.bank_questions("it", 3, 1)}
        ik = {q["question"] for q in iv.bank_questions("ik", 3, 1)}
        self.assertTrue(any("VLAN" in q or "GPO" in q or "Firewall" in q or "internet" in q for q in it))
        self.assertTrue(any("işe alım" in q.lower() or "yetkinlik" in q.lower() for q in ik))
        self.assertFalse(it & ik)

    def test_ai_questions_used_and_bad_ones_dropped(self):
        fake = {"questions": [
            {"stage": "technical", "question": "CV'nizde 300 kullanıcılı ağ yazıyor; VLAN'ları nasıl böldünüz?", "expects": "x"},
            {"stage": "technical", "question": "Kısa?", "expects": "x"},                                  # çok kısa
            {"stage": "behavioral", "question": "Bir hatanızdan ne öğrendiniz?", "expects": "STAR"},
        ]}
        with mock.patch("ai_engine.brain._chat_json", return_value=fake):
            qs, err = iv.plan_interview(PROFILE, "it", n_tech=2, n_beh=1)
        tech = [q for q in qs if q["stage"] == "technical"]
        self.assertEqual(tech[0]["source"], "yapay zekâ")
        self.assertEqual(len(tech), 2)                      # eksik kalan bankadan tamamlandı
        self.assertEqual(tech[1]["source"], "banka")
        self.assertIsNone(err)

    def test_ai_failure_falls_back(self):
        with mock.patch("ai_engine.brain._chat_json", side_effect=RuntimeError("zaman aşımı")):
            qs, err = iv.plan_interview(PROFILE, "it", n_tech=2, n_beh=1)
        self.assertIn("zaman aşımı", err)
        self.assertEqual(len(qs), 6)


class EvaluateTests(unittest.TestCase):
    Q_BEH = {"stage": "behavioral", "question": "Baskı altında çözdüğünüz bir arızayı anlatır mısınız?", "expects": "STAR"}
    Q_TECH = {"stage": "technical", "question": "VLAN nedir?", "expects": "802.1Q"}

    def test_empty_answer(self):
        ev = iv.evaluate(self.Q_TECH, "", PROFILE, use_ai=False)
        self.assertEqual(ev["score"], 1)

    def test_rule_signals(self):
        good = ("Geçen yıl bir gün çekirdek switch arızalandı ve 300 kullanıcı internetsiz kaldı. Ben hemen logları "
                "inceledim, arızalı portu tespit ettim ve trafiği yedek switche aldım. Sonunda kesinti 25 dakikada bitti.")
        ev = iv.evaluate(self.Q_BEH, good, PROFILE, use_ai=False)
        self.assertGreaterEqual(ev["score"], 4)
        weak = iv.evaluate(self.Q_BEH, "yani şey eee bir arıza oldu yani şey çözdük işte", PROFILE, use_ai=False)
        self.assertLessEqual(weak["score"], 2)
        self.assertTrue(any("STAR" in s for s in weak["improve"]))
        self.assertGreaterEqual(weak["signals"]["fillers"], 4)

    def test_fabricated_better_answer_hidden(self):
        fake = {"score": 4, "strengths": ["Net"], "improve": ["Sayı ekleyin"],
                "better": "Kubernetes ile 5000 podluk kümeyi yönettim.", "followup": "Hangi araçları kullandınız?"}
        with mock.patch("ai_engine.brain._chat_json", return_value=fake):
            ev = iv.evaluate(self.Q_TECH, "VLAN yayın alanını böler, trunk ile taşırım.", PROFILE, "it", cv_text=CV)
        self.assertEqual(ev["better"], "")                   # Kubernetes / 5000 adayda yok → gösterilmez
        self.assertEqual(ev["followup"], "Hangi araçları kullandınız?")
        self.assertEqual(ev["score"], 4)

    def test_placeholder_better_answer_kept(self):
        fake = {"score": 3, "strengths": [], "improve": [], "better": "Cisco switchlerde VLAN'ları [sayı] departmana böldüm.",
                "followup": ""}
        with mock.patch("ai_engine.brain._chat_json", return_value=fake):
            ev = iv.evaluate(self.Q_TECH, "VLAN ile ağı böldüm.", PROFILE, "it", cv_text=CV)
        self.assertIn("[sayı]", ev["better"])

    def test_ai_error_uses_rules(self):
        with mock.patch("ai_engine.brain._chat_json", side_effect=RuntimeError("kapalı")):
            ev = iv.evaluate(self.Q_TECH, "VLAN yayın alanını böler.", PROFILE)
        self.assertEqual(ev["source"], "kural")
        self.assertIn("kapalı", ev["ai_error"])


class ReportTests(unittest.TestCase):
    def test_report(self):
        sig = {"words": 50, "fillers": 2}
        results = [
            {"question": {"stage": "technical"}, "answer": "a", "eval": {"score": 4, "strengths": ["Sayı verdi"], "improve": ["Kısa"], "signals": sig}},
            {"question": {"stage": "technical"}, "answer": "b", "eval": {"score": 2, "strengths": [], "improve": ["Kısa"], "signals": sig}},
            {"question": {"stage": "behavioral"}, "answer": "c", "eval": {"score": 5, "strengths": ["Sayı verdi"], "improve": [], "signals": sig}},
        ]
        r = iv.report(results)
        self.assertEqual(r["overall"], round(11 / 3 * 20))
        self.assertEqual(r["by_stage"], {"Teknik": 3.0, "Davranışsal": 5.0})
        self.assertEqual(r["strengths"][0], "Sayı verdi")
        self.assertEqual(r["improve"][0], "Kısa")
        self.assertEqual((r["words"], r["fillers"]), (150, 6))

    def test_sessions_saved_and_listed(self):
        d = tempfile.mkdtemp()
        with mock.patch("ai_engine.cv_studio.PROFILES_DIR", d):
            iv.save_session("u", {"title": "Sistem Uzmanı", "report": {"overall": 72}, "results": [1, 2]})
            rows = iv.list_sessions("u")
        self.assertEqual((rows[0]["Pozisyon"], rows[0]["Puan"], rows[0]["Soru"]), ("Sistem Uzmanı", 72, 2))


class VoiceTests(unittest.TestCase):
    def wav(self, rate, channels=1, seconds=1.0):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            t = np.arange(int(rate * seconds))
            tone = (np.sin(2 * np.pi * 440 * t / rate) * 12000).astype(np.int16)
            w.writeframes(np.repeat(tone, channels).tobytes())
        return buf.getvalue()

    def test_resample_to_16k_mono(self):
        a = voice.wav_to_array(self.wav(48000, channels=2, seconds=1.0))
        self.assertEqual(a.dtype, np.float32)
        self.assertEqual(len(a), 16000)
        self.assertLessEqual(float(np.abs(a).max()), 1.0)

    def test_bad_audio(self):
        with self.assertRaises(voice.VoiceError):
            voice.wav_to_array(b"bu bir ses dosyasi degil")

    def test_too_short_recording_is_empty(self):
        with mock.patch.object(voice, "stt_available", return_value=True), \
                mock.patch.dict("sys.modules", {"mlx_whisper": mock.MagicMock()}):
            self.assertEqual(voice.transcribe(self.wav(16000, seconds=0.2)), "")


if __name__ == "__main__":
    unittest.main()
