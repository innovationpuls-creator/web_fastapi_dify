from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import unittest

from fastapi.testclient import TestClient

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.infrastructure.persistence import ChatRepository, NewMessagePart
from backend.app.core.container import AppContainer
from backend.app.core.openai_client import OpenAIGateway
from backend.app.core.settings import get_settings
from backend.app.main import create_app


class FakeGateway(OpenAIGateway):
    def __init__(self) -> None:
        self.client = None  # type: ignore[assignment]

    async def create_chat_stream(self, request_args):  # type: ignore[override]
        raise AssertionError(f"Unexpected chat stream call: {request_args}")

    async def probe_health(self, *, model: str, timeout) -> None:  # type: ignore[override]
        return None

    async def close(self) -> None:  # type: ignore[override]
        return None


class ChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_path = Path("backend/tests/.tmp_api")
        shutil.rmtree(self.base_path, ignore_errors=True)
        self.base_path.mkdir(parents=True, exist_ok=True)
        os.environ.update(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "http://127.0.0.1:1234/v1",
                "OPENAI_MODEL": "test-model",
                "CHAT_DATABASE_PATH": str(self.base_path / "chat.sqlite3"),
                "CHAT_ASSETS_DIR": str(self.base_path / "chat-assets"),
                "CHAT_UPLOADS_DIR": str(self.base_path / "chat-uploads"),
            }
        )
        get_settings.cache_clear()
        self.settings = get_settings()
        self.repository = ChatRepository(
            self.settings.chat_database_path,
            self.settings.chat_assets_dir,
            self.settings.chat_uploads_dir,
        )
        asyncio.run(self.repository.initialize())
        self.registry = ChatCancellationRegistry()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        shutil.rmtree(self.base_path, ignore_errors=True)

    def _create_client(self) -> TestClient:
        def container_factory(settings) -> AppContainer:
            return AppContainer(
                settings=settings,
                chat_repository=self.repository,
                chat_cancellation_registry=self.registry,
                openai_gateway=FakeGateway(),
            )

        return TestClient(create_app(container_factory=container_factory))

    def test_get_chat_conversations_returns_seeded_summary(self) -> None:
        conversation = asyncio.run(
            self.repository.create_conversation(
                title="API conversation",
                created_at="2026-03-08T10:00:00+00:00",
            )
        )
        asyncio.run(
            self.repository.create_message(
                conversation_id=conversation.id,
                role="user",
                status="completed",
                preview_text="hello",
                text_content="hello",
                parts=[NewMessagePart(type="text", text="hello")],
                created_at="2026-03-08T10:00:01+00:00",
            )
        )

        with self._create_client() as client:
            response = client.get("/chat/conversations")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(conversation.id, [item["id"] for item in payload])
        self.assertIn("API conversation", [item["title"] for item in payload])

    def test_get_missing_chat_conversation_returns_api_error(self) -> None:
        with self._create_client() as client:
            response = client.get("/chat/conversations/missing-conversation")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["detail"], "Conversation not found.")
        self.assertIn("request_id", payload)

    def test_cancel_message_uses_new_chat_conversations_route(self) -> None:
        conversation = asyncio.run(
            self.repository.create_conversation(
                title="Cancel API",
                created_at="2026-03-08T11:00:00+00:00",
            )
        )
        asyncio.run(
            self.repository.create_message(
                conversation_id=conversation.id,
                message_id="user-msg",
                role="user",
                status="completed",
                preview_text="hello",
                text_content="hello",
                parts=[NewMessagePart(type="text", text="hello")],
                created_at="2026-03-08T11:00:01+00:00",
            )
        )
        assistant = asyncio.run(
            self.repository.create_message(
                conversation_id=conversation.id,
                message_id="assistant-msg",
                role="assistant",
                status="streaming",
                preview_text="Thinking...",
                text_content="partial",
                parts=[],
                created_at="2026-03-08T11:00:02+00:00",
                model="test-model",
            )
        )
        asyncio.run(
            self.registry.register(
                conversation_id=conversation.id,
                message_id=assistant.id,
                model="test-model",
                created_at=assistant.created_at,
            )
        )

        with self._create_client() as client:
            response = client.post(
                f"/chat/conversations/{conversation.id}/messages/{assistant.id}/cancel"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["message"]["status"], "cancelled")
        self.assertEqual(payload["conversation"]["id"], conversation.id)
