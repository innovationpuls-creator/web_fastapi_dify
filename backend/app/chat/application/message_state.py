from __future__ import annotations

from backend.app.chat.domain.constants import (
    PUBLIC_CANCELLED_FINISH_REASON,
    PUBLIC_CANCELLED_PREVIEW,
)
from backend.app.chat.domain.text import preview_from_text
from backend.app.chat.infrastructure.persistence import ChatRepository, MessageRecord


async def persist_cancelled_message(
    *,
    repository: ChatRepository,
    message_id: str,
    partial_text: str,
    updated_at: str,
    model: str | None,
    thinking_completed_at: str | None = None,
) -> MessageRecord | None:
    existing = await repository.get_message(message_id)
    if existing is None:
        return None
    if existing.status == "cancelled":
        return existing
    return await repository.update_message(
        message_id=message_id,
        status="cancelled",
        preview_text=preview_from_text(partial_text, fallback=PUBLIC_CANCELLED_PREVIEW),
        text_content=partial_text,
        updated_at=updated_at,
        model=model,
        finish_reason=PUBLIC_CANCELLED_FINISH_REASON,
        error=None,
        thinking_completed_at=thinking_completed_at,
    )
