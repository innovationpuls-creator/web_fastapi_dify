from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.application.message_state import persist_cancelled_message
from backend.app.chat.application.presenters import (
    conversation_to_detail,
    conversation_to_summary,
    message_to_response,
)
from backend.app.chat.domain.text import utc_now
from backend.app.chat.infrastructure.file_store import delete_paths
from backend.app.chat.infrastructure.persistence import (
    AssetRecord,
    ChatRepository,
    UploadRecord,
)
from backend.app.chat.schemas import CancelMessageResponse, ConversationDetail, ConversationSummary


@dataclass(slots=True)
class ConversationService:
    repository: ChatRepository
    cancellation_registry: ChatCancellationRegistry

    async def list_conversations(self) -> list[ConversationSummary]:
        conversations = await self.repository.list_conversations()
        return [conversation_to_summary(item) for item in conversations]

    async def get_conversation_detail(
        self,
        conversation_id: str,
    ) -> ConversationDetail | None:
        detail = await self.repository.get_conversation_detail(conversation_id)
        if detail is None:
            return None
        conversation, messages = detail
        return conversation_to_detail(conversation, messages)

    async def delete_conversation(self, conversation_id: str) -> bool:
        deleted_paths = await self.repository.delete_conversation(conversation_id)
        if deleted_paths is None:
            return False
        await delete_paths(deleted_paths)
        return True

    async def cancel_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> CancelMessageResponse | None:
        message = await self.repository.get_message(message_id)
        if (
            message is None
            or message.conversation_id != conversation_id
            or message.role != "assistant"
        ):
            return None

        now = utc_now()
        snapshot = await self.cancellation_registry.request_cancel(
            conversation_id=conversation_id,
            message_id=message_id,
            updated_at=now,
        )

        if snapshot is not None:
            updated_message = await persist_cancelled_message(
                repository=self.repository,
                message_id=message_id,
                partial_text=snapshot.text_content,
                updated_at=now,
                model=snapshot.model or message.model,
            )
            conversation = await self.repository.get_conversation(conversation_id)
            if updated_message is None or conversation is None:
                return None
            return CancelMessageResponse(
                message=message_to_response(updated_message),
                conversation=conversation_to_summary(conversation),
            )

        if message.status == "streaming":
            updated_message = await persist_cancelled_message(
                repository=self.repository,
                message_id=message_id,
                partial_text=message.text_content,
                updated_at=now,
                model=message.model,
            )
            conversation = await self.repository.get_conversation(conversation_id)
            if updated_message is None or conversation is None:
                return None
            return CancelMessageResponse(
                message=message_to_response(updated_message),
                conversation=conversation_to_summary(conversation),
            )

        conversation = await self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        return CancelMessageResponse(
            message=message_to_response(message),
            conversation=conversation_to_summary(conversation),
        )

    async def get_asset_record(self, asset_id: str) -> AssetRecord | None:
        asset = await self.repository.get_asset(asset_id)
        if asset is None or not Path(asset.storage_path).exists():
            return None
        return asset

    async def get_upload_record(self, upload_id: str) -> UploadRecord | None:
        upload = await self.repository.get_upload(upload_id)
        if upload is None or not Path(upload.storage_path).exists():
            return None
        return upload
