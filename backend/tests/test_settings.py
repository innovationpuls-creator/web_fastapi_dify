import unittest

from backend.app.core.settings import DEFAULT_OPENAI_SYSTEM_PROMPT


class SettingsTests(unittest.TestCase):
    def test_default_system_prompt_supports_deeper_reasoning(self) -> None:
        self.assertNotIn("concise multilingual AI assistant", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertNotIn("3 short sentences", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("same language", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("Do not echo prior conversation turns", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("<think>...</think>", DEFAULT_OPENAI_SYSTEM_PROMPT)
        self.assertIn("explain by block or line", DEFAULT_OPENAI_SYSTEM_PROMPT)
