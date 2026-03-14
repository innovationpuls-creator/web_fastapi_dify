import asyncio
import unittest

from backend.app.core.dify_client import create_dify_client
from backend.app.core.settings import AppSettings, DEFAULT_OPENAI_SYSTEM_PROMPT


class SettingsTests(unittest.TestCase):
    def test_default_system_prompt_supports_deeper_reasoning(self) -> None:
        self.assertNotIn("concise multilingual AI assistant", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertNotIn("3 short sentences", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("same language", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("Do not echo prior conversation turns", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("<think>...</think>", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("explain by block or line", DEFAULT_OPENAI_SYSTEM_PROMPT)

    def test_dify_enabled_requires_non_empty_api_key(self) -> None:
        disabled = AppSettings(
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1234/v1",
            openai_model="test-model",
            dify_api_key="",
        )
        enabled = AppSettings(
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1234/v1",
            openai_model="test-model",
            dify_api_key="test-dify-key",
        )

        self.assertFalse(disabled.dify_enabled)
        self.assertTrue(enabled.dify_enabled)

    def test_dify_default_inputs_expose_backend_fallback_values(self) -> None:
        settings = AppSettings(
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1234/v1",
            openai_model="test-model",
            dify_api_key="test-dify-key",
            dify_target_score_outline=88,
            dify_target_score_draft=92,
        )

        self.assertEqual(
            settings.dify_default_inputs,
            {
                "target_score_outline": 88,
                "target_score_draft": 92,
            },
        )

    def test_dify_client_uses_dedicated_timeout_settings(self) -> None:
        settings = AppSettings(
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1234/v1",
            openai_model="test-model",
            dify_api_key="test-dify-key",
            dify_connect_timeout_seconds=7,
            dify_read_timeout_seconds=222,
            dify_write_timeout_seconds=11,
        )

        client = create_dify_client(settings)

        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(client.timeout.connect, 7)
        self.assertEqual(client.timeout.read, 222)
        self.assertEqual(client.timeout.write, 11)
        self.assertEqual(client.timeout.pool, 7)

        asyncio.run(client.aclose())
