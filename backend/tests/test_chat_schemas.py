from __future__ import annotations

import unittest

from backend.app.chat.schemas import ChatStreamRequest


class ChatSchemaTests(unittest.TestCase):
    def test_chat_stream_request_accepts_text_and_image_parts(self) -> None:
        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "Analyze this"},
                        {
                            "type": "image",
                            "media_type": "image/webp",
                            "data_base64": "UklGRlIAAABXRUJQVlA4",
                        },
                    ]
                },
                "generation": {"temperature": 0.5, "max_output_tokens": 256},
            }
        )

        self.assertEqual(payload.input.parts[0].type, "text")
        self.assertEqual(payload.input.parts[1].type, "image")
        self.assertEqual(payload.generation.max_output_tokens, 256)

    def test_chat_stream_request_accepts_uploaded_image_part(self) -> None:
        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "Analyze this"},
                        {"type": "image", "upload_id": "upload-12345678"},
                    ]
                }
            }
        )

        self.assertEqual(payload.input.parts[1].upload_id, "upload-12345678")
        self.assertIsNone(payload.input.parts[1].data_base64)

    def test_chat_stream_request_uses_default_output_token_budget(self) -> None:
        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "Hello"},
                    ]
                }
            }
        )

        self.assertEqual(payload.generation.max_output_tokens, 2048)
