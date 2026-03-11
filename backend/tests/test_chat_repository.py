from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from backend.app.chat.infrastructure.persistence import (
    ChatRepository,
    NewAsset,
    NewMessagePart,
)


class ChatRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base_path = Path("backend/tests/.tmp_repo")
        shutil.rmtree(self.base_path, ignore_errors=True)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.repository = ChatRepository(
            self.base_path / "chat.sqlite3",
            self.base_path / "assets",
            self.base_path / "uploads",
        )
        await self.repository.initialize()

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.base_path, ignore_errors=True)

    async def test_create_detail_update_and_delete_conversation(self) -> None:
        conversation = await self.repository.create_conversation(
            title="Test conversation",
            created_at="2026-03-06T12:00:00+00:00",
        )

        message = await self.repository.create_message(
            conversation_id=conversation.id,
            role="user",
            status="completed",
            preview_text="hello",
            text_content="hello",
            parts=[
                NewMessagePart(type="text", text="hello"),
                NewMessagePart(
                    type="image",
                    asset=NewAsset(
                        id="asset-1",
                        media_type="image/webp",
                        storage_path=str(self.base_path / "assets" / "asset-1.webp"),
                        byte_size=128,
                    ),
                ),
            ],
            created_at="2026-03-06T12:00:01+00:00",
        )

        updated_message = await self.repository.update_message(
            message_id=message.id,
            status="completed",
            preview_text="assistant reply",
            text_content="assistant reply",
            updated_at="2026-03-06T12:00:02+00:00",
            model="qwen/qwen3.5-9b",
        )

        detail = await self.repository.get_conversation_detail(conversation.id)
        self.assertIsNotNone(detail)
        loaded_conversation, messages = detail or (None, [])
        self.assertEqual(loaded_conversation.message_count, 1)
        self.assertEqual(messages[0].text_content, "assistant reply")
        self.assertEqual(messages[0].parts[0].type, "text")
        self.assertEqual(messages[0].model, "qwen/qwen3.5-9b")
        self.assertIsNotNone(updated_message)

        deleted_paths = await self.repository.delete_conversation(conversation.id)
        self.assertEqual(deleted_paths, [self.base_path / "assets" / "asset-1.webp"])
        self.assertIsNone(await self.repository.get_conversation(conversation.id))

    async def test_initialize_creates_schema_supporting_cancelled_status(self) -> None:
        repository = ChatRepository(
            self.base_path / "cancelled.sqlite3",
            self.base_path / "cancelled-assets",
            self.base_path / "cancelled-uploads",
        )
        await repository.initialize()
        conversation = await repository.create_conversation(
            title="Cancelled conversation",
            created_at="2026-03-06T13:00:00+00:00",
        )

        message = await repository.create_message(
            conversation_id=conversation.id,
            role="assistant",
            status="cancelled",
            preview_text="Generation cancelled.",
            text_content="partial output",
            parts=[NewMessagePart(type="text", text="partial output")],
            created_at="2026-03-06T13:00:01+00:00",
        )

        self.assertEqual(message.status, "cancelled")

    async def test_create_pop_delete_and_expire_uploads(self) -> None:
        created = await self.repository.create_upload(
            upload_id="upload-1",
            media_type="image/webp",
            storage_path=str(self.base_path / "uploads" / "upload-1.webp"),
            byte_size=256,
            created_at="2026-03-06T10:00:00+00:00",
        )

        loaded = await self.repository.get_upload(created.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.media_type, "image/webp")

        popped = await self.repository.pop_upload(created.id)
        self.assertIsNotNone(popped)
        self.assertEqual(popped.id, created.id)
        self.assertIsNone(await self.repository.get_upload(created.id))

        second = await self.repository.create_upload(
            upload_id="upload-2",
            media_type="image/png",
            storage_path=str(self.base_path / "uploads" / "upload-2.png"),
            byte_size=512,
            created_at="2026-03-06T11:00:00+00:00",
        )
        deleted_path = await self.repository.delete_upload(second.id)
        self.assertEqual(deleted_path, self.base_path / "uploads" / "upload-2.png")
        self.assertIsNone(await self.repository.get_upload(second.id))

        await self.repository.create_upload(
            upload_id="upload-old",
            media_type="image/png",
            storage_path=str(self.base_path / "uploads" / "upload-old.png"),
            byte_size=128,
            created_at="2026-03-06T08:00:00+00:00",
        )
        await self.repository.create_upload(
            upload_id="upload-fresh",
            media_type="image/png",
            storage_path=str(self.base_path / "uploads" / "upload-fresh.png"),
            byte_size=128,
            created_at="2026-03-06T12:00:00+00:00",
        )
        expired_paths = await self.repository.delete_expired_uploads(
            "2026-03-06T09:00:00+00:00"
        )
        self.assertEqual(expired_paths, [self.base_path / "uploads" / "upload-old.png"])
        self.assertIsNone(await self.repository.get_upload("upload-old"))
        self.assertIsNotNone(await self.repository.get_upload("upload-fresh"))

    async def test_conversation_detail_keeps_user_before_assistant_for_same_timestamp(self) -> None:
        conversation = await self.repository.create_conversation(
            title="Same timestamp ordering",
            created_at="2026-03-06T14:00:00+00:00",
        )
        shared_timestamp = "2026-03-06T14:00:01+00:00"

        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="detail-z-user",
            role="user",
            status="completed",
            preview_text="Question",
            text_content="Question",
            parts=[NewMessagePart(type="text", text="Question")],
            created_at=shared_timestamp,
        )
        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="detail-a-assistant",
            role="assistant",
            status="completed",
            preview_text="Answer",
            text_content="Answer",
            parts=[NewMessagePart(type="text", text="Answer")],
            created_at=shared_timestamp,
        )

        detail = await self.repository.get_conversation_detail(conversation.id)

        self.assertIsNotNone(detail)
        _, messages = detail or (None, [])
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(
            [message.id for message in messages],
            ["detail-z-user", "detail-a-assistant"],
        )

    async def test_conversation_preview_prefers_assistant_for_same_timestamp_turn(self) -> None:
        conversation = await self.repository.create_conversation(
            title="Preview ordering",
            created_at="2026-03-06T15:00:00+00:00",
        )
        shared_timestamp = "2026-03-06T15:00:01+00:00"

        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="preview-z-user",
            role="user",
            status="completed",
            preview_text="Question",
            text_content="Question",
            parts=[NewMessagePart(type="text", text="Question")],
            created_at=shared_timestamp,
        )
        await self.repository.create_message(
            conversation_id=conversation.id,
            message_id="preview-a-assistant",
            role="assistant",
            status="completed",
            preview_text="Answer",
            text_content="Answer",
            parts=[NewMessagePart(type="text", text="Answer")],
            created_at=shared_timestamp,
        )

        summary = await self.repository.get_conversation(conversation.id)
        conversations = await self.repository.list_conversations()

        self.assertIsNotNone(summary)
        self.assertEqual(summary.last_message_preview, "Answer")
        self.assertEqual(conversations[0].last_message_preview, "Answer")
