from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest

from backend.app.chat.application.conversations import ConversationService
from backend.app.chat.application.message_state import persist_cancelled_message
from backend.app.chat.application.streaming import (
    ChatStreamService,
    PreparedChatStream,
    build_chat_request_args,
)
from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.domain.errors import ChatPreStreamError
from backend.app.chat.domain.text import utc_now
from backend.app.chat.infrastructure.persistence import (
    ChatRepository,
    NewAsset,
    NewMessagePart,
)
from backend.app.chat.schemas import ChatStreamRequest


class FakeChunkChoice:
    def __init__(self, delta: str = "", finish_reason: str | None = None) -> None:
        self.delta = SimpleNamespace(content=delta)
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(
        self,
        delta: str = "",
        finish_reason: str | None = None,
        usage: object | None = None,
    ) -> None:
        self.choices = [FakeChunkChoice(delta=delta, finish_reason=finish_reason)]
        self.usage = usage


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

    async def _seed_completed_turn(
        self,
        *,
        user_text: str = "Original question",
        assistant_text: str = "Original answer",
        include_image: bool = False,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        conversation = await self.repository.create_conversation(
            title="Completed turn",
            created_at="2026-03-07T00:00:00+00:00",
        )
        user_parts = [NewMessagePart(type="text", text=user_text)]
        if include_image:
            user_parts.append(
                NewMessagePart(
                    type="image",
                    asset=NewAsset(
                        id="asset-1",
                        media_type="image/webp",
                        storage_path=str(self.base_path / "assets" / "asset-1.webp"),
                        byte_size=128,
                    ),
                )
            )
        user_message = await self.repository.create_message(
            conversation_id=conversation.id,
            role="user",
            status="completed",
            preview_text=user_text,
            text_content=user_text,
            parts=user_parts,
            created_at="2026-03-07T00:00:01+00:00",
        )
        assistant_message = await self.repository.create_message(
            conversation_id=conversation.id,
            role="assistant",
            status="completed",
            preview_text=assistant_text,
            text_content=assistant_text,
            parts=[NewMessagePart(type="text", text=assistant_text)],
            created_at="2026-03-07T00:00:02+00:00",
            model="test-model",
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
            latency_ms=432.1,
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

    async def test_persist_cancelled_message_backfills_thinking_completion_time(self) -> None:
        _, messages = await self._seed_streaming_assistant()
        cancelled_message = await self.repository.update_message(
            message_id=messages.assistant.id,
            status="cancelled",
            preview_text="Generation cancelled.",
            text_content="Partial answer",
            updated_at="2026-03-07T00:00:03+00:00",
            model="test-model",
            finish_reason="cancelled",
            error=None,
            thinking_completed_at=None,
        )

        self.assertIsNotNone(cancelled_message)
        self.assertIsNone(cancelled_message.thinking_completed_at)

        backfilled = await persist_cancelled_message(
            repository=self.repository,
            message_id=messages.assistant.id,
            partial_text="Partial answer",
            updated_at="2026-03-07T00:00:04+00:00",
            model="test-model",
            thinking_completed_at="2026-03-07T00:00:02.500000+00:00",
        )

        self.assertIsNotNone(backfilled)
        self.assertEqual(
            backfilled.thinking_completed_at,
            "2026-03-07T00:00:02.500000+00:00",
        )
        self.assertEqual(backfilled.status, "cancelled")

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(
            stored_message.thinking_completed_at,
            "2026-03-07T00:00:02.500000+00:00",
        )
        self.assertEqual(stored_message.text_content, "Partial answer")

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

    async def test_generate_chat_stream_persists_usage_and_latency_metrics(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        prepared = PreparedChatStream(
            stream=FakeStream(
                [
                    (0.0, FakeChunk(delta="Measured answer")),
                    (
                        0.0,
                        FakeChunk(
                            finish_reason="stop",
                            usage=SimpleNamespace(
                                prompt_tokens=120,
                                completion_tokens=42,
                                total_tokens=162,
                            ),
                        ),
                    ),
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
        self.assertEqual(events[-1]["message"]["metrics"]["input_tokens"], 120)
        self.assertEqual(events[-1]["message"]["metrics"]["output_tokens"], 42)
        self.assertEqual(events[-1]["message"]["metrics"]["total_tokens"], 162)
        self.assertIsNotNone(events[-1]["message"]["metrics"]["latency_ms"])

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message.input_tokens, 120)
        self.assertEqual(stored_message.output_tokens, 42)
        self.assertEqual(stored_message.total_tokens, 162)
        self.assertIsNotNone(stored_message.latency_ms)
        self.assertGreater(stored_message.latency_ms, 0)

    async def test_generate_chat_stream_persists_thinking_completion_time(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        prepared = PreparedChatStream(
            stream=FakeStream(
                [
                    (0.0, FakeChunk(delta="<think>Plan")),
                    (0.02, FakeChunk(delta=" carefully</think>")),
                    (0.02, FakeChunk(delta=" Final answer")),
                    (0.0, FakeChunk(finish_reason="stop")),
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

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertIsNotNone(stored_message.thinking_completed_at)
        self.assertNotEqual(
            stored_message.thinking_completed_at,
            stored_message.updated_at,
        )
        self.assertEqual(
            events[-1]["message"]["thinking_completed_at"],
            stored_message.thinking_completed_at,
        )

    async def test_cancelled_stream_preserves_thinking_completion_time(self) -> None:
        conversation, messages = await self._seed_streaming_assistant()
        request = FakeRequest()
        stream_service = self._create_stream_service()
        conversation_service = ConversationService(self.repository, self.registry)
        prepared = PreparedChatStream(
            stream=FakeStream(
                [
                    (0.0, FakeChunk(delta="<think>Plan")),
                    (0.0, FakeChunk(delta=" carefully</think>")),
                    (0.0, FakeChunk(delta=" Partial answer")),
                    (0.5, FakeChunk(delta=" more")),
                ]
            ),
            start_time=0.0,
            message_count=1,
            model="test-model",
            conversation=conversation,
            user_message=messages.user,
            assistant_message=messages.assistant,
        )

        third_delta_seen = asyncio.Event()
        delta_count = 0

        async def consume() -> None:
            nonlocal delta_count
            async for payload in stream_service.generate_chat_stream(request, prepared):
                event = json.loads(payload.decode("utf-8"))
                if event["event"] == "delta":
                    delta_count += 1
                    if delta_count == 3:
                        third_delta_seen.set()

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(third_delta_seen.wait(), timeout=1)
        await asyncio.sleep(0.02)

        cancelled = await conversation_service.cancel_message(
            conversation.id,
            messages.assistant.id,
        )
        await asyncio.wait_for(consumer, timeout=1)

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.message.status, "cancelled")
        self.assertIsNotNone(cancelled.message.thinking_completed_at)
        self.assertNotEqual(
            cancelled.message.thinking_completed_at,
            cancelled.message.updated_at,
        )

        stored_message = await self.repository.get_message(messages.assistant.id)
        self.assertIsNotNone(stored_message)
        self.assertEqual(
            stored_message.thinking_completed_at,
            cancelled.message.thinking_completed_at,
        )

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

    async def test_prepare_edit_stream_rewrites_last_text_turn(self) -> None:
        conversation, messages = await self._seed_completed_turn()
        stream = FakeStream(
            [
                (0.0, FakeChunk(delta="Edited answer")),
                (0.0, FakeChunk(finish_reason="stop")),
            ]
        )
        stream_service = self._create_stream_service(stream)
        payload = ChatStreamRequest.model_validate(
            {
                "input": {"parts": [{"type": "text", "text": "Edited question"}]},
            }
        )

        prepared = await stream_service.prepare_edit_stream(
            FakeRequest(
                path=(
                    f"/chat/conversations/{conversation.id}/messages/"
                    f"{messages.user.id}/edit-stream"
                )
            ),
            conversation.id,
            messages.user.id,
            payload,
        )

        rewritten_user = await self.repository.get_message(messages.user.id)
        rewritten_assistant = await self.repository.get_message(messages.assistant.id)

        self.assertIsNotNone(rewritten_user)
        self.assertIsNotNone(rewritten_assistant)
        self.assertEqual(rewritten_user.text_content, "Edited question")
        self.assertEqual(rewritten_assistant.status, "streaming")
        self.assertEqual(rewritten_assistant.text_content, "")
        self.assertIsNone(rewritten_assistant.total_tokens)
        self.assertNotEqual(rewritten_assistant.created_at, messages.assistant.created_at)
        self.assertEqual(prepared.assistant_message.id, messages.assistant.id)

        events: list[dict[str, object]] = []
        async for payload_bytes in stream_service.generate_chat_stream(FakeRequest(), prepared):
            events.append(json.loads(payload_bytes.decode("utf-8")))

        self.assertEqual(events[-1]["message"]["parts"][0]["text"], "Edited answer")

    async def test_prepare_edit_stream_rejects_last_turn_with_image(self) -> None:
        conversation, messages = await self._seed_completed_turn(include_image=True)
        stream_service = self._create_stream_service()
        payload = ChatStreamRequest.model_validate(
            {
                "input": {"parts": [{"type": "text", "text": "Edited question"}]},
            }
        )

        with self.assertRaises(ChatPreStreamError) as context:
            await stream_service.prepare_edit_stream(
                FakeRequest(
                    path=(
                        f"/chat/conversations/{conversation.id}/messages/"
                        f"{messages.user.id}/edit-stream"
                    )
                ),
                conversation.id,
                messages.user.id,
                payload,
            )

        self.assertEqual(context.exception.status_code, 409)

    async def test_prepare_regenerate_stream_reuses_last_turn_input(self) -> None:
        conversation, messages = await self._seed_completed_turn()
        stream = FakeStream(
            [
                (0.0, FakeChunk(delta="Regenerated answer")),
                (
                    0.0,
                    FakeChunk(
                        finish_reason="stop",
                        usage={
                            "prompt_tokens": 15,
                            "completion_tokens": 6,
                            "total_tokens": 21,
                        },
                    ),
                ),
            ]
        )
        stream_service = self._create_stream_service(stream)
        generation = ChatStreamRequest.model_validate(
            {"input": {"parts": [{"type": "text", "text": "ignored"}]}}
        ).generation

        prepared = await stream_service.prepare_regenerate_stream(
            FakeRequest(
                path=(
                    f"/chat/conversations/{conversation.id}/messages/"
                    f"{messages.assistant.id}/regenerate-stream"
                )
            ),
            conversation.id,
            messages.assistant.id,
            generation,
        )

        self.assertIsNotNone(stream_service.openai_gateway.last_request_args)
        upstream_messages = stream_service.openai_gateway.last_request_args["messages"]
        self.assertEqual(upstream_messages[1]["content"], "Original question")
        self.assertEqual(prepared.user_message.id, messages.user.id)
        self.assertEqual(prepared.assistant_message.id, messages.assistant.id)
        self.assertNotEqual(prepared.assistant_message.created_at, messages.assistant.created_at)

    async def test_prepare_regenerate_stream_rejects_non_last_assistant(self) -> None:
        conversation, messages = await self._seed_completed_turn()
        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="user-newer",
            role="user",
            status="completed",
            preview_text="Newer question",
            text_content="Newer question",
            parts=[NewMessagePart(type="text", text="Newer question")],
            created_at="2026-03-07T00:00:03+00:00",
        )
        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="assistant-newer",
            role="assistant",
            status="completed",
            preview_text="Newer answer",
            text_content="Newer answer",
            parts=[NewMessagePart(type="text", text="Newer answer")],
            created_at="2026-03-07T00:00:04+00:00",
            model="test-model",
        )
        stream_service = self._create_stream_service()
        generation = ChatStreamRequest.model_validate(
            {"input": {"parts": [{"type": "text", "text": "ignored"}]}}
        ).generation

        with self.assertRaises(ChatPreStreamError) as context:
            await stream_service.prepare_regenerate_stream(
                FakeRequest(
                    path=(
                        f"/chat/conversations/{conversation.id}/messages/"
                        f"{messages.assistant.id}/regenerate-stream"
                    )
                ),
                conversation.id,
                messages.assistant.id,
                generation,
            )

        self.assertEqual(context.exception.status_code, 409)
