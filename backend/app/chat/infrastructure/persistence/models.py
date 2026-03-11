from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["completed", "streaming", "failed", "cancelled"]
MessagePartType = Literal["text", "image"]


@dataclass(frozen=True)
class UploadRecord:
    id: str
    media_type: str
    storage_path: str
    byte_size: int
    created_at: str


@dataclass(frozen=True)
class AssetRecord:
    id: str
    message_id: str
    media_type: str
    storage_path: str
    byte_size: int
    created_at: str


@dataclass(frozen=True)
class MessagePartRecord:
    type: MessagePartType
    text: str | None = None
    asset: AssetRecord | None = None


@dataclass(frozen=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: MessageRole
    status: MessageStatus
    preview_text: str
    text_content: str
    model: str | None
    finish_reason: str | None
    error: str | None
    created_at: str
    updated_at: str
    parts: list[MessagePartRecord]


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    title: str
    created_at: str
    updated_at: str
    last_message_preview: str
    message_count: int


@dataclass(frozen=True)
class NewAsset:
    media_type: str
    storage_path: str
    byte_size: int
    id: str = ""

    def with_id(self) -> "NewAsset":
        return NewAsset(
            id=self.id or uuid4().hex,
            media_type=self.media_type,
            storage_path=self.storage_path,
            byte_size=self.byte_size,
        )


@dataclass(frozen=True)
class NewMessagePart:
    type: MessagePartType
    text: str | None = None
    asset: NewAsset | None = None
