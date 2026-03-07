"""Chat service for conversation-driven multimodal streaming."""

from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import re
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import Request, UploadFile
from openai import AsyncOpenAI, OpenAIError

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.repository import (
    AssetRecord,
    ChatRepository,
    ConversationRecord,
    MessagePartRecord,
    MessageRecord,
    NewAsset,
    NewMessagePart,
    UploadRecord,
)
from backend.app.chat.schemas import (
    CancelMessageResponse,
    ChatMessageResponse,
    ChatStreamEvent,
    ChatStreamRequest,
    ChatUploadResponse,
    ConversationDetail,
    ConversationSummary,
    ImageInputPart,
    ImageMessagePart,
    InputPart,
    MessagePart,
    TextInputPart,
    TextMessagePart,
)
from backend.app.core.api_errors import build_api_error_response
from backend.app.core.settings import AppSettings

logger = logging.getLogger(__name__)

NDJSON_MEDIA_TYPE = "application/x-ndjson"
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
PUBLIC_UPSTREAM_ERROR = "Upstream chat service unavailable."
PUBLIC_STREAM_ERROR = "Upstream chat stream interrupted."
PUBLIC_INVALID_IMAGE_ERROR = "Image attachment is invalid."
PUBLIC_UPLOAD_NOT_FOUND_ERROR = "Image upload not found."
PUBLIC_UPLOAD_UNSUPPORTED_ERROR = "Only PNG, JPEG, and WEBP images are supported."
PUBLIC_CANCELLED_PREVIEW = "Generation cancelled."
PUBLIC_CANCELLED_FINISH_REASON = "cancelled"
IMAGE_EXTENSION_BY_MEDIA_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?(?:</think\s*>|$)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class PreparedImage:
    media_type: str
    inline_bytes: bytes | None = None
    upload: UploadRecord | None = None


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


class ChatPreStreamError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        upstream_error: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.upstream_error = upstream_error


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _timestamp_title() -> str:
    return datetime.now(UTC).strftime("Conversation %Y-%m-%d %H:%M UTC")


def _log_context(
    request: Request,
    model: str,
    message_count: int,
    duration_ms: float | str = "-",
    status_code: int | str = "-",
) -> dict[str, Any]:
    return {
        "request_id": getattr(request.state, "request_id", "-"),
        "feature": "chat",
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "client_ip": _client_ip(request),
        "model": model,
        "message_count": message_count,
    }


def serialize_event(event: ChatStreamEvent) -> bytes:
    return f"{event.model_dump_json()}\n".encode("utf-8")


def build_chat_error_response(request: Request, exc: ChatPreStreamError):
    return build_api_error_response(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=getattr(request.state, "request_id", "-"),
        upstream_error=exc.upstream_error,
    )


def _repository(request: Request) -> ChatRepository:
    return request.app.state.chat_repository


def _cancellation_registry(request: Request) -> ChatCancellationRegistry:
    return request.app.state.chat_cancellation_registry


def _strip_visible_preview(value: str, *, fallback: str) -> str:
    collapsed = " ".join(value.split())
    return (collapsed[:117] + "...") if len(collapsed) > 120 else (collapsed or fallback)


def _derive_title(parts: list[InputPart]) -> str:
    for part in parts:
        if isinstance(part, TextInputPart):
            cleaned = " ".join(part.text.split())
            if cleaned:
                return cleaned[:40]
    return _timestamp_title()


def _preview_from_input_parts(parts: list[InputPart]) -> str:
    texts = [
        " ".join(part.text.split())
        for part in parts
        if isinstance(part, TextInputPart) and part.text.strip()
    ]
    if texts:
        return _strip_visible_preview(" ".join(texts), fallback="New message")
    image_count = sum(1 for part in parts if isinstance(part, ImageInputPart))
    return "[Image]" if image_count == 1 else f"[{image_count} images]"


def _strip_reasoning_blocks(value: str) -> str:
    stripped = THINK_BLOCK_PATTERN.sub("", value)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _preview_from_text(value: str, *, fallback: str) -> str:
    visible_text = _strip_reasoning_blocks(value)
    return _strip_visible_preview(visible_text, fallback=fallback)


def _normalize_base64(data: str) -> bytes:
    payload = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ChatPreStreamError(
            status_code=422,
            detail=PUBLIC_INVALID_IMAGE_ERROR,
        ) from exc


def _asset_url(asset_id: str) -> str:
    return f"/chat/assets/{asset_id}"


def _upload_url(upload_id: str) -> str:
    return f"/chat/uploads/{upload_id}"


async def _write_bytes(path: Path, data: bytes) -> None:
    await asyncio.to_thread(path.write_bytes, data)


async def _move_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(source.replace, destination)


async def _read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def _unlink_many(paths: list[Path]) -> None:
    async def _unlink(path: Path) -> None:
        await asyncio.to_thread(path.unlink, missing_ok=True)

    await asyncio.gather(*[_unlink(path) for path in paths], return_exceptions=True)


def _expired_upload_cutoff(settings: AppSettings) -> str:
    return (
        datetime.now(UTC) - timedelta(seconds=settings.chat_upload_ttl_seconds)
    ).isoformat(timespec="seconds")


async def purge_expired_uploads(request: Request) -> None:
    settings: AppSettings = request.app.state.settings
    repository = _repository(request)
    expired_paths = await repository.delete_expired_uploads(_expired_upload_cutoff(settings))
    await _unlink_many(expired_paths)


async def _prepare_input(
    *,
    parts: list[InputPart],
    settings: AppSettings,
    repository: ChatRepository,
) -> PreparedInput:
    image_parts = [part for part in parts if isinstance(part, ImageInputPart)]
    if len(image_parts) > settings.chat_max_images_per_message:
        raise ChatPreStreamError(
            status_code=422,
            detail=(
                f"At most {settings.chat_max_images_per_message} image(s) are allowed "
                "per message."
            ),
        )

    images: list[PreparedImage] = []
    text_parts: list[str] = []

    for part in parts:
        if isinstance(part, TextInputPart):
            cleaned = part.text.strip()
            if cleaned:
                text_parts.append(cleaned)
            continue

        if part.upload_id:
            upload = await repository.get_upload(part.upload_id)
            if upload is None or not Path(upload.storage_path).exists():
                raise ChatPreStreamError(
                    status_code=422,
                    detail=PUBLIC_UPLOAD_NOT_FOUND_ERROR,
                )
            images.append(PreparedImage(media_type=upload.media_type, upload=upload))
            continue

        image_bytes = _normalize_base64(part.data_base64 or "")
        if len(image_bytes) > settings.chat_max_image_bytes:
            raise ChatPreStreamError(
                status_code=422,
                detail=(
                    f"Image exceeds the {settings.chat_max_image_bytes} byte limit."
                ),
            )
        images.append(
            PreparedImage(
                media_type=part.media_type or "image/webp",
                inline_bytes=image_bytes,
            )
        )

    if not text_parts and not images:
        raise ChatPreStreamError(
            status_code=422,
            detail="Message must contain visible text or at least one image.",
        )

    return PreparedInput(
        text_parts=text_parts,
        images=images,
        preview_text=_preview_from_input_parts(parts),
        title_text=_derive_title(parts),
    )


def _message_part_to_schema(part: MessagePartRecord) -> MessagePart:
    if part.type == "image" and part.asset is not None:
        return ImageMessagePart(
            type="image",
            asset_id=part.asset.id,
            media_type=part.asset.media_type,
            url=_asset_url(part.asset.id),
        )
    return TextMessagePart(type="text", text=part.text or "")


def message_to_response(message: MessageRecord) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        status=message.status,
        parts=[_message_part_to_schema(part) for part in message.parts],
        created_at=message.created_at,
        updated_at=message.updated_at,
        model=message.model,
        finish_reason=message.finish_reason,
        error=message.error,
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
    conversation: ConversationRecord, messages: list[MessageRecord]
) -> ConversationDetail:
    return ConversationDetail(
        **conversation_to_summary(conversation).model_dump(),
        messages=[message_to_response(message) for message in messages],
    )


async def _persist_cancelled_message(
    *,
    repository: ChatRepository,
    message_id: str,
    partial_text: str,
    updated_at: str,
    model: str | None,
) -> MessageRecord | None:
    existing = await repository.get_message(message_id)
    if existing is None:
        return None
    if existing.status == "cancelled":
        return existing
    return await repository.update_message(
        message_id=message_id,
        status="cancelled",
        preview_text=_preview_from_text(partial_text, fallback=PUBLIC_CANCELLED_PREVIEW),
        text_content=partial_text,
        updated_at=updated_at,
        model=model,
        finish_reason=PUBLIC_CANCELLED_FINISH_REASON,
        error=None,
    )


async def _build_upstream_messages(messages: list[MessageRecord]) -> list[dict[str, Any]]:
    upstream_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            if not message.text_content:
                continue
            upstream_messages.append({"role": "assistant", "content": message.text_content})
            continue

        text_segments: list[str] = []
        content_parts: list[dict[str, Any]] = []
        has_images = False
        for part in message.parts:
            if part.type == "text" and part.text:
                text_segments.append(part.text)
                content_parts.append({"type": "text", "text": part.text})
                continue
            if part.type == "image" and part.asset:
                has_images = True
                asset_bytes = await _read_bytes(Path(part.asset.storage_path))
                encoded = base64.b64encode(asset_bytes).decode("ascii")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{part.asset.media_type};base64,{encoded}",
                            "detail": "auto",
                        },
                    }
                )
        if not content_parts:
            continue
        if has_images:
            upstream_messages.append({"role": "user", "content": content_parts})
        else:
            upstream_messages.append({"role": "user", "content": "\n\n".join(text_segments)})
    return upstream_messages


async def _build_current_turn_message(prepared_input: PreparedInput) -> dict[str, Any]:
    content_parts: list[dict[str, Any]] = []
    for text in prepared_input.text_parts:
        content_parts.append({"type": "text", "text": text})

    if not prepared_input.images:
        return {"role": "user", "content": "\n\n".join(prepared_input.text_parts)}

    for image in prepared_input.images:
        image_bytes = (
            image.inline_bytes
            if image.inline_bytes is not None
            else await _read_bytes(Path(image.upload.storage_path))
        )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image.media_type};base64,{encoded}",
                    "detail": "auto",
                },
            }
        )
    return {"role": "user", "content": content_parts}


async def _persist_prepared_input(
    *,
    prepared_input: PreparedInput,
    message_id: str,
    repository: ChatRepository,
) -> tuple[list[NewMessagePart], list[Path]]:
    parts: list[NewMessagePart] = [
        NewMessagePart(type="text", text=text) for text in prepared_input.text_parts
    ]
    created_paths: list[Path] = []

    for image in prepared_input.images:
        asset_id = image.upload.id if image.upload is not None else uuid4().hex
        extension = IMAGE_EXTENSION_BY_MEDIA_TYPE[image.media_type]
        asset_path = repository.assets_dir / f"{message_id}_{asset_id}{extension}"

        if image.inline_bytes is not None:
            await _write_bytes(asset_path, image.inline_bytes)
        else:
            claimed_upload = await repository.pop_upload(image.upload.id)
            if claimed_upload is None or not Path(claimed_upload.storage_path).exists():
                raise ChatPreStreamError(
                    status_code=422,
                    detail=PUBLIC_UPLOAD_NOT_FOUND_ERROR,
                )
            await _move_path(Path(claimed_upload.storage_path), asset_path)

        created_paths.append(asset_path)
        parts.append(
            NewMessagePart(
                type="image",
                asset=NewAsset(
                    id=asset_id,
                    media_type=image.media_type,
                    storage_path=str(asset_path),
                    byte_size=asset_path.stat().st_size,
                ),
            )
        )

    return parts, created_paths


def build_chat_request_args(
    payload: ChatStreamRequest,
    settings: AppSettings,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    upstream_messages = [
        {"role": "system", "content": settings.openai_system_prompt},
        *messages,
    ]
    request_args: dict[str, Any] = {
        "model": settings.openai_model,
        "messages": upstream_messages,
        "temperature": payload.generation.temperature,
        "stream": True,
    }
    if payload.generation.max_output_tokens is not None:
        request_args["max_tokens"] = payload.generation.max_output_tokens
    return request_args


def _extract_delta_content(delta_content: Any) -> str:
    if isinstance(delta_content, str):
        return delta_content
    if isinstance(delta_content, list):
        parts: list[str] = []
        for item in delta_content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
                continue
            text_value = getattr(item, "text", None)
            if isinstance(text_value, str):
                parts.append(text_value)
        return "".join(parts)
    return ""


async def _cancel_pending_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def list_conversations(request: Request) -> list[ConversationSummary]:
    conversations = await _repository(request).list_conversations()
    return [conversation_to_summary(item) for item in conversations]


async def get_conversation_detail(
    request: Request, conversation_id: str
) -> ConversationDetail | None:
    detail = await _repository(request).get_conversation_detail(conversation_id)
    if detail is None:
        return None
    conversation, messages = detail
    return conversation_to_detail(conversation, messages)


async def get_asset_record(request: Request, asset_id: str) -> AssetRecord | None:
    return await _repository(request).get_asset(asset_id)


async def get_upload_record(request: Request, upload_id: str) -> UploadRecord | None:
    return await _repository(request).get_upload(upload_id)


async def delete_conversation(request: Request, conversation_id: str) -> bool:
    deleted_paths = await _repository(request).delete_conversation(conversation_id)
    if deleted_paths is None:
        return False
    await _unlink_many(deleted_paths)
    return True


async def upload_chat_file(
    request: Request,
    file: UploadFile,
) -> ChatUploadResponse:
    settings: AppSettings = request.app.state.settings
    repository = _repository(request)
    await purge_expired_uploads(request)

    media_type = file.content_type or ""
    if media_type not in IMAGE_EXTENSION_BY_MEDIA_TYPE:
        raise ChatPreStreamError(
            status_code=422,
            detail=PUBLIC_UPLOAD_UNSUPPORTED_ERROR,
        )

    payload = await file.read()
    await file.close()
    if not payload:
        raise ChatPreStreamError(status_code=422, detail=PUBLIC_INVALID_IMAGE_ERROR)
    if len(payload) > settings.chat_max_image_bytes:
        raise ChatPreStreamError(
            status_code=422,
            detail=f"Image exceeds the {settings.chat_max_image_bytes} byte limit.",
        )

    upload_id = uuid4().hex
    extension = IMAGE_EXTENSION_BY_MEDIA_TYPE[media_type]
    upload_path = repository.uploads_dir / f"{upload_id}{extension}"
    await _write_bytes(upload_path, payload)

    record = await repository.create_upload(
        upload_id=upload_id,
        media_type=media_type,
        storage_path=str(upload_path),
        byte_size=len(payload),
        created_at=_utc_now(),
    )
    return ChatUploadResponse(
        upload_id=record.id,
        url=_upload_url(record.id),
        media_type=record.media_type,
        byte_size=record.byte_size,
        created_at=record.created_at,
    )


async def delete_upload(request: Request, upload_id: str) -> bool:
    deleted_path = await _repository(request).delete_upload(upload_id)
    if deleted_path is None:
        return False
    await _unlink_many([deleted_path])
    return True


async def cancel_message(
    request: Request,
    conversation_id: str,
    message_id: str,
) -> CancelMessageResponse | None:
    repository = _repository(request)
    registry = _cancellation_registry(request)
    message = await repository.get_message(message_id)
    if (
        message is None
        or message.conversation_id != conversation_id
        or message.role != "assistant"
    ):
        return None

    now = _utc_now()
    snapshot = await registry.request_cancel(
        conversation_id=conversation_id,
        message_id=message_id,
        updated_at=now,
    )

    if snapshot is not None:
        updated_message = await _persist_cancelled_message(
            repository=repository,
            message_id=message_id,
            partial_text=snapshot.text_content,
            updated_at=now,
            model=snapshot.model or message.model,
        )
        conversation = await repository.get_conversation(conversation_id)
        if updated_message is None or conversation is None:
            return None
        return CancelMessageResponse(
            message=message_to_response(updated_message),
            conversation=conversation_to_summary(conversation),
        )

    if message.status == "streaming":
        updated_message = await _persist_cancelled_message(
            repository=repository,
            message_id=message_id,
            partial_text=message.text_content,
            updated_at=now,
            model=message.model,
        )
        conversation = await repository.get_conversation(conversation_id)
        if updated_message is None or conversation is None:
            return None
        return CancelMessageResponse(
            message=message_to_response(updated_message),
            conversation=conversation_to_summary(conversation),
        )

    conversation = await repository.get_conversation(conversation_id)
    if conversation is None:
        return None
    return CancelMessageResponse(
        message=message_to_response(message),
        conversation=conversation_to_summary(conversation),
    )


async def prepare_chat_stream(
    request: Request,
    payload: ChatStreamRequest,
) -> PreparedChatStream:
    settings: AppSettings = request.app.state.settings
    repository = _repository(request)
    client: AsyncOpenAI = request.app.state.openai_client
    start_time = time.perf_counter()
    now = _utc_now()
    user_message_id = uuid4().hex
    await purge_expired_uploads(request)

    conversation_created = False
    if payload.conversation_id:
        conversation = await repository.get_conversation(payload.conversation_id)
        if conversation is None:
            raise ChatPreStreamError(status_code=404, detail="Conversation not found.")
    else:
        conversation = await repository.create_conversation(
            title=_derive_title(payload.input.parts),
            created_at=now,
        )
        conversation_created = True

    try:
        prepared_input = await _prepare_input(
            parts=payload.input.parts,
            settings=settings,
            repository=repository,
        )
    except ChatPreStreamError:
        if conversation_created:
            await repository.delete_conversation(conversation.id)
        raise

    logger.info(
        "chat_stream_started",
        extra=_log_context(request, settings.openai_model, message_count=0),
    )

    try:
        history = await repository.list_messages(conversation.id)
        upstream_messages = await _build_upstream_messages(history)
        upstream_messages.append(await _build_current_turn_message(prepared_input))
        stream = await client.chat.completions.create(
            **build_chat_request_args(payload, settings, upstream_messages)
        )
    except OpenAIError as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            "chat_stream_upstream_error",
            extra=_log_context(
                request,
                settings.openai_model,
                message_count=len(upstream_messages) if "upstream_messages" in locals() else 0,
                duration_ms=duration_ms,
                status_code=502,
            ),
        )
        if conversation_created:
            await repository.delete_conversation(conversation.id)
        raise ChatPreStreamError(
            status_code=502,
            detail="Upstream chat stream could not be established.",
            upstream_error=PUBLIC_UPSTREAM_ERROR,
        ) from exc
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            "chat_stream_prepare_failed",
            extra=_log_context(
                request,
                settings.openai_model,
                message_count=len(upstream_messages) if "upstream_messages" in locals() else 0,
                duration_ms=duration_ms,
                status_code=500,
            ),
        )
        if conversation_created:
            await repository.delete_conversation(conversation.id)
        raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

    created_asset_paths: list[Path] = []
    try:
        user_message_parts, created_asset_paths = await _persist_prepared_input(
            prepared_input=prepared_input,
            message_id=user_message_id,
            repository=repository,
        )
        user_message = await repository.create_message(
            conversation_id=conversation.id,
            message_id=user_message_id,
            role="user",
            status="completed",
            preview_text=prepared_input.preview_text,
            text_content="\n\n".join(prepared_input.text_parts),
            parts=user_message_parts,
            created_at=now,
        )
        assistant_message = await repository.create_message(
            conversation_id=conversation.id,
            message_id=uuid4().hex,
            role="assistant",
            status="streaming",
            preview_text="Thinking...",
            text_content="",
            parts=[],
            created_at=_utc_now(),
            model=settings.openai_model,
        )
    except ChatPreStreamError:
        await stream.close()
        await _unlink_many(created_asset_paths)
        if conversation_created:
            await repository.delete_conversation(conversation.id)
        raise
    except Exception as exc:
        await stream.close()
        await _unlink_many(created_asset_paths)
        if conversation_created:
            await repository.delete_conversation(conversation.id)
        raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

    await _cancellation_registry(request).register(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        model=settings.openai_model,
        created_at=assistant_message.created_at,
    )
    refreshed_conversation = await repository.get_conversation(conversation.id)
    return PreparedChatStream(
        stream=stream,
        start_time=start_time,
        message_count=len(upstream_messages),
        model=settings.openai_model,
        conversation=refreshed_conversation or conversation,
        user_message=user_message,
        assistant_message=assistant_message,
    )


async def generate_chat_stream(
    request: Request,
    prepared_stream: PreparedChatStream,
) -> AsyncGenerator[bytes, None]:
    repository = _repository(request)
    registry = _cancellation_registry(request)
    full_content_parts: list[str] = []
    finish_reason: str | None = None
    stream = prepared_stream.stream
    start_time = prepared_stream.start_time
    chunk_count = 0
    first_chunk_logged = False
    cancel_event = await registry.cancel_event(prepared_stream.assistant_message.id)
    if cancel_event is None:
        cancel_event = asyncio.Event()

    async def finish_as_cancelled() -> tuple[MessageRecord | None, ConversationRecord | None]:
        partial_text = "".join(full_content_parts)
        updated_message = await _persist_cancelled_message(
            repository=repository,
            message_id=prepared_stream.assistant_message.id,
            partial_text=partial_text,
            updated_at=_utc_now(),
            model=prepared_stream.model,
        )
        updated_conversation = await repository.get_conversation(
            prepared_stream.conversation.id
        )
        return updated_message, updated_conversation

    yield serialize_event(
        ChatStreamEvent(
            event="meta",
            model=prepared_stream.model,
            conversation_id=prepared_stream.conversation.id,
            user_message_id=prepared_stream.user_message.id,
            assistant_message_id=prepared_stream.assistant_message.id,
            title=prepared_stream.conversation.title,
        )
    )

    try:
        stream_iterator = stream.__aiter__()
        while True:
            next_chunk_task = asyncio.create_task(anext(stream_iterator))
            cancel_wait_task = asyncio.create_task(cancel_event.wait())
            done, pending = await asyncio.wait(
                {next_chunk_task, cancel_wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                await _cancel_pending_task(pending_task)

            if cancel_wait_task in done and cancel_event.is_set():
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                updated_message, updated_conversation = await finish_as_cancelled()
                logger.info(
                    "chat_stream_cancelled",
                    extra=_log_context(
                        request,
                        prepared_stream.model,
                        prepared_stream.message_count,
                        duration_ms=duration_ms,
                        status_code=499,
                    ),
                )
                if (
                    updated_message is not None
                    and updated_conversation is not None
                    and not await request.is_disconnected()
                ):
                    yield serialize_event(
                        ChatStreamEvent(
                            event="done",
                            model=prepared_stream.model,
                            conversation_id=updated_conversation.id,
                            assistant_message_id=updated_message.id,
                            message=message_to_response(updated_message),
                            conversation=conversation_to_summary(updated_conversation),
                            finish_reason=PUBLIC_CANCELLED_FINISH_REASON,
                        )
                    )
                return

            try:
                chunk = next_chunk_task.result()
            except StopAsyncIteration:
                break

            if await request.is_disconnected():
                if cancel_event.is_set():
                    await finish_as_cancelled()
                    return
                partial_text = "".join(full_content_parts)
                await repository.update_message(
                    message_id=prepared_stream.assistant_message.id,
                    status="failed",
                    preview_text=_preview_from_text(
                        partial_text, fallback="Generation cancelled"
                    ),
                    text_content=partial_text,
                    updated_at=_utc_now(),
                    model=prepared_stream.model,
                    error="Client disconnected.",
                )
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                logger.warning(
                    "chat_stream_client_disconnected",
                    extra=_log_context(
                        request,
                        prepared_stream.model,
                        prepared_stream.message_count,
                        duration_ms=duration_ms,
                    ),
                )
                return

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = _extract_delta_content(choice.delta.content)
            if not delta:
                continue

            if not first_chunk_logged:
                first_chunk_logged = True
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                logger.info(
                    "chat_stream_first_chunk",
                    extra=_log_context(
                        request,
                        prepared_stream.model,
                        prepared_stream.message_count,
                        duration_ms=duration_ms,
                        status_code=200,
                    ),
                )

            chunk_count += 1
            full_content_parts.append(delta)
            await registry.append_text(
                prepared_stream.assistant_message.id,
                delta,
                updated_at=_utc_now(),
            )
            yield serialize_event(
                ChatStreamEvent(
                    event="delta",
                    model=prepared_stream.model,
                    conversation_id=prepared_stream.conversation.id,
                    assistant_message_id=prepared_stream.assistant_message.id,
                    delta=delta,
                )
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        final_text = "".join(full_content_parts)
        updated_message = await repository.update_message(
            message_id=prepared_stream.assistant_message.id,
            status="completed",
            preview_text=_preview_from_text(final_text, fallback="Assistant reply"),
            text_content=final_text,
            updated_at=_utc_now(),
            model=prepared_stream.model,
            finish_reason=finish_reason,
            error=None,
        )
        updated_conversation = await repository.get_conversation(
            prepared_stream.conversation.id
        )
        if updated_message and updated_conversation:
            yield serialize_event(
                ChatStreamEvent(
                    event="done",
                    model=prepared_stream.model,
                    conversation_id=updated_conversation.id,
                    assistant_message_id=updated_message.id,
                    message=message_to_response(updated_message),
                    conversation=conversation_to_summary(updated_conversation),
                    finish_reason=finish_reason,
                )
            )
        logger.info(
            "chat_stream_completed chunks=%s",
            chunk_count,
            extra=_log_context(
                request,
                prepared_stream.model,
                prepared_stream.message_count,
                duration_ms=duration_ms,
                status_code=200,
            ),
        )
    except OpenAIError:
        if cancel_event.is_set():
            await finish_as_cancelled()
            return
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        partial_text = "".join(full_content_parts)
        await repository.update_message(
            message_id=prepared_stream.assistant_message.id,
            status="failed",
            preview_text=_preview_from_text(partial_text, fallback="Generation failed"),
            text_content=partial_text,
            updated_at=_utc_now(),
            model=prepared_stream.model,
            finish_reason=finish_reason,
            error=PUBLIC_STREAM_ERROR,
        )
        logger.exception(
            "chat_stream_upstream_error",
            extra=_log_context(
                request,
                prepared_stream.model,
                prepared_stream.message_count,
                duration_ms=duration_ms,
                status_code=502,
            ),
        )
        if not await request.is_disconnected():
            yield serialize_event(
                ChatStreamEvent(
                    event="error",
                    model=prepared_stream.model,
                    conversation_id=prepared_stream.conversation.id,
                    assistant_message_id=prepared_stream.assistant_message.id,
                    error=PUBLIC_STREAM_ERROR,
                )
            )
    except Exception:
        if cancel_event.is_set():
            await finish_as_cancelled()
            return
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        partial_text = "".join(full_content_parts)
        await repository.update_message(
            message_id=prepared_stream.assistant_message.id,
            status="failed",
            preview_text=_preview_from_text(partial_text, fallback="Generation failed"),
            text_content=partial_text,
            updated_at=_utc_now(),
            model=prepared_stream.model,
            finish_reason=finish_reason,
            error="Internal server error.",
        )
        logger.exception(
            "chat_stream_unexpected_error",
            extra=_log_context(
                request,
                prepared_stream.model,
                prepared_stream.message_count,
                duration_ms=duration_ms,
                status_code=500,
            ),
        )
        if not await request.is_disconnected():
            yield serialize_event(
                ChatStreamEvent(
                    event="error",
                    model=prepared_stream.model,
                    conversation_id=prepared_stream.conversation.id,
                    assistant_message_id=prepared_stream.assistant_message.id,
                    error="Internal server error.",
                )
            )
    finally:
        await registry.unregister(prepared_stream.assistant_message.id)
        await stream.close()
