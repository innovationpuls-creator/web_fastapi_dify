from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest

from backend.app.chat.application.conversations import ConversationService
from backend.app.chat.application.streaming import (
    ChatStreamService,
    PreparedChatStream,
    build_chat_request_args,
)
from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.domain.text import utc_now
from backend.app.chat.infrastructure.persistence import ChatRepository, NewMessagePart
from backend.app.chat.schemas import ChatStreamRequest


class FakeChunkChoice:
    def __init__(self, delta: str = "", finish_reason: str | None = None) -> None:
        self.delta = SimpleNamespace(content=delta)
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(self, delta: str = "", finish_reason: str | None = None) -> None:
        self.choices = [FakeChunkChoice(delta=delta, finish_reason=finish_reason)]


class FakeStream:
    def __init__(self, items: list[tuple[float, FakeChunk]]) -> None:
        self.items = items
        self.index = 0
        self.closed = False

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> FakeChunk:
        if self.closed or self.index >= len(self.items):
            raise StopAsyncIteration

        delay, item = self.items[self.index]
        self.index += 1
        if delay:
            await asyncio.sleep(delay)
        if self.closed:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True


class FakeGateway:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream
        self.last_request_args: dict[str, object] | None = None

    async def create_chat_stream(self, request_args: dict[str, object]) -> FakeStream:
        self.last_request_args = dict(request_args)
        return self.stream

    async def probe_health(self, **_: object) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeRequest:
    def __init__(self, *, path: str = "/chat/stream") -> None:
        self.state = SimpleNamespace(request_id="test-request")
        self.method = "POST"
        self.url = SimpleNamespace(path=path)
        self.client = SimpleNamespace(host="127.0.0.1")
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected

    def disconnect(self) -> None:
        self._disconnected = True


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base_path = Path("backend/tests/.tmp_service")
        shutil.rmtree(self.base_path, ignore_errors=True)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.repository = ChatRepository(
            self.base_path / "chat.sqlite3",
            self.base_path / "assets",
            self.base_path / "uploads",
        )
        await self.repository.initialize()
        self.registry = ChatCancellationRegistry()
        self.settings = SimpleNamespace(
            openai_model="test-model",
            openai_system_prompt="Test system prompt.",
            chat_max_images_per_message=4,
            chat_max_image_bytes=5_000_000,
            chat_upload_ttl_seconds=3600,
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.base_path, ignore_errors=True)

    async def _seed_streaming_assistant(self) -> tuple[SimpleNamespace, SimpleNamespace]:
        conversation = await self.repository.create_conversation(
            title="Cancel test",
            created_at="2026-03-07T00:00:00+00:00",
        )
        user_message = await self.repository.create_message(
            conversation_id=conversation.id,
            role="user",
            status="completed",
            preview_text="hello",
            text_content="hello",
            parts=[NewMessagePart(type="text", text="hello")],
            created_at="2026-03-07T00:00:01+00:00",
        )
        assistant_message = await self.repository.create_message(
            conversation_id=conversation.id,
            role="assistant",
            status="streaming",
            preview_text="Thinking...",
            text_content="",
            parts=[],
            created_at="2026-03-07T00:00:02+00:00",
            model="test-model",
        )
        await self.registry.register(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            model="test-model",
            created_at=assistant_message.created_at,
        )
        return conversation, SimpleNamespace(user=user_message, assistant=assistant_message)

    def _create_stream_service(self, stream: FakeStream | None = None) -> ChatStreamService:
        return ChatStreamService(
            repository=self.repository,
            cancellation_registry=self.registry,
            openai_gateway=FakeGateway(stream or FakeStream([])),
            settings=self.settings,
        )

    async def test_generate_chat_stream_persists_cancelled_message(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        conversation_service = ConversationService(self.repository, self.registry)
        stream = FakeStream(
            [
                (0.0, FakeChunk(delta="Hello")),
                (0.5, FakeChunk(delta=" world")),
            ]
        )
        prepared = PreparedChatStream(
            stream=stream,
            start_time=0.0,
            message_count=1,
            model="test-model",
            conversation=conversation,
            user_message=messages.user,
            assistant_message=messages.assistant,
        )

        events: list[dict[str, object]] = []
        first_delta_seen = asyncio.Event()

        async def consume() -> None:
            async for payload in stream_service.generate_chat_stream(request, prepared):
                event = json.loads(payload.decode("utf-8"))
                events.append(event)
                if event["event"] == "delta":
                    first_delta_seen.set()

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(first_delta_seen.wait(), timeout=1)

        cancelled = await conversation_service.cancel_message(
            conversation.id,
            messages.assistant.id,
        )
        await asyncio.wait_for(consumer, timeout=1)

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.message.status, "cancelled")
        self.assertEqual(cancelled.message.parts[0].text, "Hello")
        self.assertEqual(events[-1]["event"], "done")
        self.assertEqual(events[-1]["finish_reason"], "cancelled")

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message.status, "cancelled")
        self.assertEqual(stored_message.text_content, "Hello")

    async def test_cancel_message_is_idempotent(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        conversation_service = ConversationService(self.repository, self.registry)

        first = await conversation_service.cancel_message(
            conversation.id,
            messages.assistant.id,
        )
        second = await conversation_service.cancel_message(
            conversation.id,
            messages.assistant.id,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.message.status, "cancelled")
        self.assertEqual(second.message.status, "cancelled")

    async def test_disconnect_without_cancel_marks_message_failed(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        stream = FakeStream(
            [
                (0.0, FakeChunk(delta="Hello")),
                (0.5, FakeChunk(delta=" world")),
            ]
        )
        prepared = PreparedChatStream(
            stream=stream,
            start_time=0.0,
            message_count=1,
            model="test-model",
            conversation=conversation,
            user_message=messages.user,
            assistant_message=messages.assistant,
        )

        first_delta_seen = asyncio.Event()

        async def consume() -> None:
            async for payload in stream_service.generate_chat_stream(request, prepared):
                event = json.loads(payload.decode("utf-8"))
                if event["event"] == "delta":
                    first_delta_seen.set()

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(first_delta_seen.wait(), timeout=1)
        request.disconnect()
        await asyncio.wait_for(consumer, timeout=1)

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message.status, "failed")
        self.assertEqual(stored_message.error, "Client disconnected.")

    async def test_cancelled_beats_disconnect(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        conversation_service = ConversationService(self.repository, self.registry)
        stream = FakeStream(
            [
                (0.0, FakeChunk(delta="Hello")),
                (0.5, FakeChunk(delta=" world")),
            ]
        )
        prepared = PreparedChatStream(
            stream=stream,
            start_time=0.0,
            message_count=1,
            model="test-model",
            conversation=conversation,
            user_message=messages.user,
            assistant_message=messages.assistant,
        )

        first_delta_seen = asyncio.Event()

        async def consume() -> None:
            async for payload in stream_service.generate_chat_stream(request, prepared):
                event = json.loads(payload.decode("utf-8"))
                if event["event"] == "delta":
                    first_delta_seen.set()

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(first_delta_seen.wait(), timeout=1)
        await conversation_service.cancel_message(conversation.id, messages.assistant.id)
        request.disconnect()
        await asyncio.wait_for(consumer, timeout=1)

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message.status, "cancelled")

    async def test_generate_chat_stream_persists_length_finish_reason(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        prepared = PreparedChatStream(
            stream=FakeStream(
                [
                    (0.0, FakeChunk(delta="Partial answer")),
                    (0.0, FakeChunk(finish_reason="length")),
                ]
            ),
            start_time=0.0,
            message_count=1,
            model="test-model",
            conversation=conversation,
            user_message=messages.user,
            assistant_message=messages.assistant,
        )

        events: list[dict[str, object]] = []

        async for payload in stream_service.generate_chat_stream(request, prepared):
            events.append(json.loads(payload.decode("utf-8")))

        self.assertEqual(events[-1]["event"], "done")
        self.assertEqual(events[-1]["finish_reason"], "length")
        self.assertEqual(events[-1]["message"]["finish_reason"], "length")

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message.status, "completed")
        self.assertEqual(stored_message.finish_reason, "length")
        self.assertEqual(stored_message.text_content, "Partial answer")

    async def test_prepare_chat_stream_consumes_uploaded_image(self) -> None:
        upload_path = self.base_path / "uploads" / "upload-image.webp"
        upload_path.write_bytes(b"RIFFmockwebp")
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        await self.repository.create_upload(
            upload_id="upload-image",
            media_type="image/webp",
            storage_path=str(upload_path),
            byte_size=upload_path.stat().st_size,
            created_at=created_at,
        )

        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "Analyze this image"},
                        {"type": "image", "upload_id": "upload-image"},
                    ]
                }
            }
        )
        gateway = FakeGateway(FakeStream([(0.0, FakeChunk(delta="ok"))]))
        stream_service = ChatStreamService(
            repository=self.repository,
            cancellation_registry=self.registry,
            openai_gateway=gateway,
            settings=self.settings,
        )

        prepared = await stream_service.prepare_chat_stream(FakeRequest(), payload)

        self.assertIsNone(await self.repository.get_upload("upload-image"))
        self.assertEqual(prepared.user_message.parts[0].type, "text")
        self.assertEqual(prepared.user_message.parts[1].type, "image")
        self.assertTrue(
            Path(prepared.user_message.parts[1].asset.storage_path).exists()
        )
        await prepared.stream.close()

    async def test_prepare_chat_stream_prepends_system_prompt(self) -> None:
        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "你好"},
                    ]
                }
            }
        )
        gateway = FakeGateway(FakeStream([(0.0, FakeChunk(delta="ok"))]))
        stream_service = ChatStreamService(
            repository=self.repository,
            cancellation_registry=self.registry,
            openai_gateway=gateway,
            settings=self.settings,
        )

        prepared = await stream_service.prepare_chat_stream(FakeRequest(), payload)

        self.assertIsNotNone(gateway.last_request_args)
        messages = gateway.last_request_args["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], self.settings.openai_system_prompt)
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "你好")
        await prepared.stream.close()

    def test_utc_now_keeps_subsecond_precision(self) -> None:
        self.assertRegex(utc_now(), r"\.\d{6}\+00:00$")

    def test_build_chat_request_args_includes_system_prompt(self) -> None:
        payload = ChatStreamRequest.model_validate(
            {
                "input": {
                    "parts": [
                        {"type": "text", "text": "hello"},
                    ]
                }
            }
        )

        request_args = build_chat_request_args(
            payload,
            self.settings,
            [{"role": "user", "content": "hello"}],
        )

        self.assertEqual(request_args["messages"][0]["role"], "system")
        self.assertEqual(
            request_args["messages"][0]["content"],
            self.settings.openai_system_prompt,
        )
        self.assertEqual(request_args["messages"][1]["content"], "hello")
