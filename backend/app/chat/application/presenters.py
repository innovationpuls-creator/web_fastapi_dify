from __future__ import annotations

from fastapi.responses import JSONResponse

from backend.app.chat.domain.errors import ChatPreStreamError
from backend.app.chat.infrastructure.persistence import (
    ConversationRecord,
    MessagePartRecord,
    MessageRecord,
)
from backend.app.chat.schemas import (
    ChatMessageResponse,
    MessageMetrics,
    ChatStreamEvent,
    ConversationDetail,
    ConversationSummary,
    ImageMessagePart,
    MessagePart,
    TextMessagePart,
)
from backend.app.core.api_errors import build_api_error_response


def asset_url(asset_id: str) -> str:
    return f"/chat/assets/{asset_id}"


def upload_url(upload_id: str) -> str:
    return f"/chat/uploads/{upload_id}"


def serialize_event(event: ChatStreamEvent) -> bytes:
    return f"{event.model_dump_json()}\n".encode("utf-8")


def build_chat_error_response(
    *,
    request_id: str,
    exc: ChatPreStreamError,
) -> JSONResponse:
    return build_api_error_response(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
        upstream_error=exc.upstream_error,
    )


def message_part_to_schema(part: MessagePartRecord) -> MessagePart:
    if part.type == "image" and part.asset is not None:
        return ImageMessagePart(
            type="image",
            asset_id=part.asset.id,
            media_type=part.asset.media_type,
            url=asset_url(part.asset.id),
        )
    return TextMessagePart(type="text", text=part.text or "")


def message_to_response(message: MessageRecord) -> ChatMessageResponse:
    metrics = None
    if message.role == "assistant":
        metrics = MessageMetrics(
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            total_tokens=message.total_tokens,
            latency_ms=message.latency_ms,
        )

    return ChatMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        status=message.status,
        parts=[message_part_to_schema(part) for part in message.parts],
        created_at=message.created_at,
        updated_at=message.updated_at,
        thinking_completed_at=message.thinking_completed_at,
        model=message.model,
        finish_reason=message.finish_reason,
        error=message.error,
        metrics=metrics,
    )


def conversation_to_summary(conversation: ConversationRecord) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_preview=conversation.last_message_preview,
        message_count=conversation.message_count,
    )


def conversation_to_detail(
    conversation: ConversationRecord,
    messages: list[MessageRecord],
) -> ConversationDetail:
    return ConversationDetail(
        **conversation_to_summary(conversation).model_dump(),
        messages=[message_to_response(message) for message in messages],
    )
