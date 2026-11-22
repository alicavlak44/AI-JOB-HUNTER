"""Bulut API (Google Gemini, OpenAI, Groq, OpenRouter) + Yerel LM Studio sağlayıcı testleri."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from openai import BadRequestError

from ai_engine import brain
from app import settings


class AIProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env_file = os.path.join(self.tmp, ".env")
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("# Yorum satırı\nCANDIDATE_NAME=Ali Cavlak\nAI_PROVIDER=local\nLM_MODEL=qwen/qwen3.5-9b\n")

    def test_save_and_reload_gemini_preserves_other_keys(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            cfg = settings.save_ai_env("gemini", api_key="AIzaTestKey123", env_path=self.env_file)
        self.assertEqual(cfg["provider"], "gemini")
        self.assertEqual(cfg["url"], "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.assertEqual(cfg["model"], "gemini-3.5-flash")
        self.assertEqual(cfg["fast_model"], "gemini-3.5-flash-lite")
        self.assertEqual(cfg["api_key"], "AIzaTestKey123")
        self.assertEqual(cfg["reasoning_effort"], "")  # bulutta 'none' gönderilmez
        self.assertTrue(cfg["is_cloud"])
        with open(self.env_file, encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("CANDIDATE_NAME=Ali Cavlak", raw)
        self.assertIn("# Yorum satırı", raw)

    def test_model_matches_gemini_prefix(self):
        self.assertTrue(brain._model_matches("gemini-2.5-flash", ["models/gemini-2.5-flash"]))
        self.assertTrue(brain._model_matches("gemini-2.5-flash", ["google/gemini-2.5-flash"]))
        self.assertFalse(brain._model_matches("gemini-2.5-pro", ["models/gemini-2.5-flash"]))

    def test_check_ai_requires_key_for_cloud(self):
        cfg = {**settings.AI_PROVIDERS["gemini"], "provider": "gemini", "api_key": "", "is_cloud": True,
               "reasoning_effort": ""}
        with mock.patch.object(brain, "_ai_cfg", return_value=cfg):
            ok, msg = brain.check_ai()
        self.assertFalse(ok)
        self.assertIn("API anahtarı eksik", msg)

    def test_check_ai_accepts_gemini_prefixed_model(self):
        cfg = {**settings.AI_PROVIDERS["gemini"], "provider": "gemini", "api_key": "AIzaOk", "is_cloud": True,
               "reasoning_effort": ""}
        fake_client = mock.MagicMock()
        fake_client.models.list.return_value.data = [SimpleNamespace(id="models/gemini-3.5-flash")]
        with mock.patch.object(brain, "_ai_cfg", return_value=cfg), \
                mock.patch.object(brain, "_client", return_value=fake_client):
            ok, msg = brain.check_ai()
        self.assertTrue(ok)
        self.assertIn("gemini-3.5-flash", msg)

    def test_chat_json_falls_back_to_json_object_on_400(self):
        cfg = {**settings.AI_PROVIDERS["gemini"], "provider": "gemini", "api_key": "AIzaOk", "is_cloud": True,
               "reasoning_effort": ""}
        fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])
        bad_req = BadRequestError("schema not supported", response=mock.MagicMock(status_code=400), body=None)
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.side_effect = [bad_req, fake_resp]
        with mock.patch.object(brain, "_ai_cfg", return_value=cfg), \
                mock.patch.object(brain, "_client", return_value=fake_client):
            out = brain._chat_json("sys", "usr", "ping", {"type": "object", "required": ["ok"]})
        self.assertEqual(out, {"ok": True})
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)
        second_kwargs = fake_client.chat.completions.create.call_args_list[1].kwargs
        self.assertEqual(second_kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", second_kwargs)


if __name__ == "__main__":
    unittest.main()
