from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.chat.infrastructure.persistence.models import (
    ConversationRecord,
    MessageRecord,
)


@dataclass(frozen=True)
class PreparedImage:
    media_type: str
    inline_bytes: bytes | None = None
    upload_id: str | None = None
    upload_storage_path: str | None = None


@dataclass(frozen=True)
class PreparedInput:
    text_parts: list[str]
    images: list[PreparedImage]
    preview_text: str
    title_text: str


@dataclass
class PreparedChatStream:
    stream: Any
    start_time: float
    message_count: int
    model: str
    conversation: ConversationRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
