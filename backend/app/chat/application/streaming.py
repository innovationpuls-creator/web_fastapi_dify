from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import Request
from openai import OpenAIError

from backend.app.chat.application.message_state import persist_cancelled_message
from backend.app.chat.application.presenters import (
    conversation_to_summary,
    message_to_response,
    serialize_event,
)
from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.domain.constants import (
    IMAGE_EXTENSION_BY_MEDIA_TYPE,
    PUBLIC_CANCELLED_FINISH_REASON,
    PUBLIC_STREAM_ERROR,
    PUBLIC_UPLOAD_NOT_FOUND_ERROR,
    PUBLIC_UPSTREAM_ERROR,
)
from backend.app.chat.domain.errors import ChatPreStreamError
from backend.app.chat.domain.media import normalize_base64
from backend.app.chat.domain.models import PreparedChatStream, PreparedImage, PreparedInput
from backend.app.chat.domain.text import (
    derive_title,
    expired_upload_cutoff,
    has_complete_thinking_block,
    preview_from_input_parts,
    preview_from_text,
    utc_now,
)
from backend.app.chat.infrastructure.file_store import (
    delete_paths,
    move_path,
    read_bytes,
    write_bytes,
)
from backend.app.chat.infrastructure.persistence import (
    ChatRepository,
    ConversationRecord,
    MessageRecord,
    NewAsset,
    NewMessagePart,
)
from backend.app.chat.schemas import (
    ChatStreamEvent,
    ChatStreamRequest,
    GenerationOptions,
    ImageInputPart,
    InputPart,
    TextInputPart,
)
from backend.app.core.openai_client import OpenAIGateway
from backend.app.core.request_context import build_log_context
from backend.app.core.settings import AppSettings

logger = logging.getLogger(__name__)


def extract_usage_metrics(chunk: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return None, None, None

    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

    return prompt_tokens, completion_tokens, total_tokens


def build_chat_request_args(
    payload: ChatStreamRequest,
    settings: AppSettings,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    return build_generation_request_args(payload.generation, settings, messages)


def build_generation_request_args(
    generation: GenerationOptions,
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
        "temperature": generation.temperature,
        "stream": True,
    }
    if generation.max_output_tokens is not None:
        request_args["max_tokens"] = generation.max_output_tokens
    return request_args


@dataclass(slots=True)
class ChatStreamService:
    repository: ChatRepository
    cancellation_registry: ChatCancellationRegistry
    openai_gateway: OpenAIGateway
    settings: AppSettings

    async def purge_expired_uploads(self) -> None:
        expired_paths = await self.repository.delete_expired_uploads(
            expired_upload_cutoff(self.settings.chat_upload_ttl_seconds)
        )
        await delete_paths(expired_paths)

    async def prepare_chat_stream(
        self,
        request: Request,
        payload: ChatStreamRequest,
    ) -> PreparedChatStream:
        start_time = time.perf_counter()
        now = utc_now()
        user_message_id = uuid4().hex
        await self.purge_expired_uploads()

        conversation_created = False
        if payload.conversation_id:
            conversation = await self.repository.get_conversation(payload.conversation_id)
            if conversation is None:
                raise ChatPreStreamError(status_code=404, detail="Conversation not found.")
        else:
            conversation = await self.repository.create_conversation(
                title=derive_title(payload.input.parts),
                created_at=now,
            )
            conversation_created = True

        try:
            prepared_input = await self._prepare_input(payload.input.parts)
        except ChatPreStreamError:
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise

        logger.info(
            "chat_stream_started",
            extra=build_log_context(
                request,
                feature="chat",
                model=self.settings.openai_model,
                message_count=0,
            ),
        )

        try:
            history = await self.repository.list_messages(conversation.id)
            upstream_messages = await self._build_upstream_messages(history)
            upstream_messages.append(await self._build_current_turn_message(prepared_input))
            stream = await self.openai_gateway.create_chat_stream(
                build_chat_request_args(payload, self.settings, upstream_messages)
            )
        except OpenAIError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_upstream_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=self.settings.openai_model,
                    message_count=len(upstream_messages)
                    if "upstream_messages" in locals()
                    else 0,
                    duration_ms=duration_ms,
                    status_code=502,
                ),
            )
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(
                status_code=502,
                detail="Upstream chat stream could not be established.",
                upstream_error=PUBLIC_UPSTREAM_ERROR,
            ) from exc
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_prepare_failed",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=self.settings.openai_model,
                    message_count=len(upstream_messages)
                    if "upstream_messages" in locals()
                    else 0,
                    duration_ms=duration_ms,
                    status_code=500,
                ),
            )
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

        created_asset_paths: list[Path] = []
        try:
            user_message_parts, created_asset_paths = await self._persist_prepared_input(
                prepared_input=prepared_input,
                message_id=user_message_id,
            )
            user_message = await self.repository.create_message(
                conversation_id=conversation.id,
                message_id=user_message_id,
                role="user",
                status="completed",
                preview_text=prepared_input.preview_text,
                text_content="\n\n".join(prepared_input.text_parts),
                parts=user_message_parts,
                created_at=now,
            )
            assistant_message = await self.repository.create_message(
                conversation_id=conversation.id,
                message_id=uuid4().hex,
                role="assistant",
                status="streaming",
                preview_text="Thinking...",
                text_content="",
                parts=[],
                created_at=utc_now(),
                model=self.settings.openai_model,
            )
        except ChatPreStreamError:
            await stream.close()
            await delete_paths(created_asset_paths)
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise
        except Exception as exc:
            await stream.close()
            await delete_paths(created_asset_paths)
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

        await self.cancellation_registry.register(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            model=self.settings.openai_model,
            created_at=assistant_message.created_at,
            thinking_completed_at=assistant_message.thinking_completed_at,
        )
        refreshed_conversation = await self.repository.get_conversation(conversation.id)
        return PreparedChatStream(
            stream=stream,
            start_time=start_time,
            message_count=len(upstream_messages),
            model=self.settings.openai_model,
            conversation=refreshed_conversation or conversation,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    async def prepare_edit_stream(
        self,
        request: Request,
        conversation_id: str,
        message_id: str,
        payload: ChatStreamRequest,
    ) -> PreparedChatStream:
        prepared_input = await self._prepare_input(payload.input.parts)
        if prepared_input.images:
            raise ChatPreStreamError(
                status_code=409,
                detail="Only the last pure-text user message can be edited.",
            )

        conversation, history, user_message, assistant_message = await self._resolve_last_turn(
            conversation_id
        )
        if user_message.id != message_id:
            raise ChatPreStreamError(
                status_code=409,
                detail="Only the last turn can be edited.",
            )
        if any(part.type == "image" for part in user_message.parts):
            raise ChatPreStreamError(
                status_code=409,
                detail="Only the last pure-text user message can be edited.",
            )

        start_time = time.perf_counter()
        upstream_messages = await self._build_upstream_messages(history)
        upstream_messages.append(await self._build_current_turn_message(prepared_input))
        stream = await self._open_stream(
            request,
            build_generation_request_args(
                payload.generation,
                self.settings,
                upstream_messages,
            ),
            len(upstream_messages),
            start_time,
        )

        updated_at = utc_now()
        refreshed_user = await self.repository.update_message(
            message_id=user_message.id,
            status="completed",
            preview_text=prepared_input.preview_text,
            text_content="\n\n".join(prepared_input.text_parts),
            updated_at=updated_at,
            created_at=user_message.created_at,
            model=None,
            finish_reason=None,
            error=None,
            thinking_completed_at=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=None,
        )
        refreshed_assistant = await self._restart_assistant_message(assistant_message.id)
        refreshed_conversation = await self.repository.get_conversation(conversation_id)
        if (
            refreshed_user is None
            or refreshed_assistant is None
            or refreshed_conversation is None
        ):
            await stream.close()
            raise ChatPreStreamError(status_code=500, detail="Internal server error.")

        return PreparedChatStream(
            stream=stream,
            start_time=start_time,
            message_count=len(upstream_messages),
            model=self.settings.openai_model,
            conversation=refreshed_conversation,
            user_message=refreshed_user,
            assistant_message=refreshed_assistant,
        )

    async def prepare_regenerate_stream(
        self,
        request: Request,
        conversation_id: str,
        message_id: str,
        generation: GenerationOptions,
    ) -> PreparedChatStream:
        conversation, history, user_message, assistant_message = await self._resolve_last_turn(
            conversation_id
        )
        if assistant_message.id != message_id:
            raise ChatPreStreamError(
                status_code=409,
                detail="Only the last assistant reply can be regenerated.",
            )

        start_time = time.perf_counter()
        prepared_input = self._prepared_input_from_message(user_message)
        upstream_messages = await self._build_upstream_messages(history)
        upstream_messages.append(await self._build_current_turn_message(prepared_input))
        stream = await self._open_stream(
            request,
            build_generation_request_args(generation, self.settings, upstream_messages),
            len(upstream_messages),
            start_time,
        )

        refreshed_assistant = await self._restart_assistant_message(assistant_message.id)
        refreshed_conversation = await self.repository.get_conversation(conversation_id)
        if refreshed_assistant is None or refreshed_conversation is None:
            await stream.close()
            raise ChatPreStreamError(status_code=500, detail="Internal server error.")

        return PreparedChatStream(
            stream=stream,
            start_time=start_time,
            message_count=len(upstream_messages),
            model=self.settings.openai_model,
            conversation=refreshed_conversation,
            user_message=user_message,
            assistant_message=refreshed_assistant,
        )

    async def generate_chat_stream(
        self,
        request: Request,
        prepared_stream: PreparedChatStream,
    ) -> AsyncGenerator[bytes, None]:
        full_content_parts: list[str] = []
        finish_reason: str | None = None
        thinking_completed_at = prepared_stream.assistant_message.thinking_completed_at
        input_tokens = prepared_stream.assistant_message.input_tokens
        output_tokens = prepared_stream.assistant_message.output_tokens
        total_tokens = prepared_stream.assistant_message.total_tokens
        stream = prepared_stream.stream
        start_time = prepared_stream.start_time
        chunk_count = 0
        first_chunk_logged = False
        cancel_event = await self.cancellation_registry.cancel_event(
            prepared_stream.assistant_message.id
        )
        if cancel_event is None:
            cancel_event = asyncio.Event()

        async def finish_as_cancelled() -> tuple[MessageRecord | None, ConversationRecord | None]:
            partial_text = "".join(full_content_parts)
            updated_message = await persist_cancelled_message(
                repository=self.repository,
                message_id=prepared_stream.assistant_message.id,
                partial_text=partial_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                thinking_completed_at=thinking_completed_at,
            )
            updated_conversation = await self.repository.get_conversation(
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
                        extra=build_log_context(
                            request,
                            feature="chat",
                            model=prepared_stream.model,
                            message_count=prepared_stream.message_count,
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
                    await self.repository.update_message(
                        message_id=prepared_stream.assistant_message.id,
                        status="failed",
                        preview_text=preview_from_text(
                            partial_text,
                            fallback="Generation cancelled",
                        ),
                        text_content=partial_text,
                        updated_at=utc_now(),
                        model=prepared_stream.model,
                        error="Client disconnected.",
                        thinking_completed_at=thinking_completed_at,
                    )
                    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    logger.warning(
                        "chat_stream_client_disconnected",
                        extra=build_log_context(
                            request,
                            feature="chat",
                            model=prepared_stream.model,
                            message_count=prepared_stream.message_count,
                            duration_ms=duration_ms,
                        ),
                    )
                    return

                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                chunk_input_tokens, chunk_output_tokens, chunk_total_tokens = (
                    extract_usage_metrics(chunk)
                )
                if chunk_input_tokens is not None:
                    input_tokens = chunk_input_tokens
                if chunk_output_tokens is not None:
                    output_tokens = chunk_output_tokens
                if chunk_total_tokens is not None:
                    total_tokens = chunk_total_tokens

                delta = _extract_delta_content(choice.delta.content)
                if not delta:
                    continue

                if not first_chunk_logged:
                    first_chunk_logged = True
                    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    logger.info(
                        "chat_stream_first_chunk",
                        extra=build_log_context(
                            request,
                            feature="chat",
                            model=prepared_stream.model,
                            message_count=prepared_stream.message_count,
                            duration_ms=duration_ms,
                            status_code=200,
                        ),
                    )

                chunk_count += 1
                full_content_parts.append(delta)
                partial_text = "".join(full_content_parts)
                delta_updated_at = utc_now()
                if (
                    thinking_completed_at is None
                    and has_complete_thinking_block(partial_text)
                ):
                    thinking_completed_at = delta_updated_at
                await self.cancellation_registry.append_text(
                    prepared_stream.assistant_message.id,
                    delta,
                    updated_at=delta_updated_at,
                    thinking_completed_at=thinking_completed_at,
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
            updated_message = await self.repository.update_message(
                message_id=prepared_stream.assistant_message.id,
                status="completed",
                preview_text=preview_from_text(final_text, fallback="Assistant reply"),
                text_content=final_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                finish_reason=finish_reason,
                error=None,
                thinking_completed_at=thinking_completed_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=duration_ms,
            )
            updated_conversation = await self.repository.get_conversation(
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
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=prepared_stream.model,
                    message_count=prepared_stream.message_count,
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
            await self.repository.update_message(
                message_id=prepared_stream.assistant_message.id,
                status="failed",
                preview_text=preview_from_text(partial_text, fallback="Generation failed"),
                text_content=partial_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                finish_reason=finish_reason,
                error=PUBLIC_STREAM_ERROR,
                thinking_completed_at=thinking_completed_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=duration_ms,
            )
            logger.exception(
                "chat_stream_upstream_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=prepared_stream.model,
                    message_count=prepared_stream.message_count,
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
            await self.repository.update_message(
                message_id=prepared_stream.assistant_message.id,
                status="failed",
                preview_text=preview_from_text(partial_text, fallback="Generation failed"),
                text_content=partial_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                finish_reason=finish_reason,
                error="Internal server error.",
                thinking_completed_at=thinking_completed_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=duration_ms,
            )
            logger.exception(
                "chat_stream_unexpected_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=prepared_stream.model,
                    message_count=prepared_stream.message_count,
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
            await self.cancellation_registry.unregister(prepared_stream.assistant_message.id)
            await stream.close()

    async def _prepare_input(self, parts: list[InputPart]) -> PreparedInput:
        image_parts = [part for part in parts if isinstance(part, ImageInputPart)]
        if len(image_parts) > self.settings.chat_max_images_per_message:
            raise ChatPreStreamError(
                status_code=422,
                detail=(
                    f"At most {self.settings.chat_max_images_per_message} image(s) are allowed "
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
                upload = await self.repository.get_upload(part.upload_id)
                if upload is None or not Path(upload.storage_path).exists():
                    raise ChatPreStreamError(
                        status_code=422,
                        detail=PUBLIC_UPLOAD_NOT_FOUND_ERROR,
                    )
                images.append(
                    PreparedImage(
                        media_type=upload.media_type,
                        upload_id=upload.id,
                        upload_storage_path=upload.storage_path,
                    )
                )
                continue

            image_bytes = normalize_base64(part.data_base64 or "")
            if len(image_bytes) > self.settings.chat_max_image_bytes:
                raise ChatPreStreamError(
                    status_code=422,
                    detail=(
                        f"Image exceeds the {self.settings.chat_max_image_bytes} byte limit."
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
            preview_text=preview_from_input_parts(parts),
            title_text=derive_title(parts),
        )

    async def _resolve_last_turn(
        self,
        conversation_id: str,
    ) -> tuple[ConversationRecord, list[MessageRecord], MessageRecord, MessageRecord]:
        conversation = await self.repository.get_conversation(conversation_id)
        if conversation is None:
            raise ChatPreStreamError(status_code=404, detail="Conversation not found.")

        messages = await self.repository.list_messages(conversation_id)
        if len(messages) < 2:
            raise ChatPreStreamError(status_code=409, detail="Only the last turn can be updated.")

        user_message = messages[-2]
        assistant_message = messages[-1]
        if user_message.role != "user" or assistant_message.role != "assistant":
            raise ChatPreStreamError(status_code=409, detail="Only the last turn can be updated.")

        return conversation, messages[:-2], user_message, assistant_message

    async def _open_stream(
        self,
        request: Request,
        request_args: dict[str, Any],
        message_count: int,
        start_time: float,
    ) -> Any:
        try:
            logger.info(
                "chat_stream_started",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=self.settings.openai_model,
                    message_count=message_count,
                ),
            )
            return await self.openai_gateway.create_chat_stream(request_args)
        except OpenAIError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_upstream_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=self.settings.openai_model,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    status_code=502,
                ),
            )
            raise ChatPreStreamError(
                status_code=502,
                detail="Upstream chat stream could not be established.",
                upstream_error=PUBLIC_UPSTREAM_ERROR,
            ) from exc
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_prepare_failed",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=self.settings.openai_model,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    status_code=500,
                ),
            )
            raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

    async def _restart_assistant_message(
        self,
        message_id: str,
    ) -> MessageRecord | None:
        restarted_at = utc_now()
        assistant_message = await self.repository.update_message(
            message_id=message_id,
            status="streaming",
            preview_text="Thinking...",
            text_content="",
            updated_at=restarted_at,
            created_at=restarted_at,
            model=self.settings.openai_model,
            finish_reason=None,
            error=None,
            thinking_completed_at=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=None,
        )
        if assistant_message is None:
            return None
        await self.cancellation_registry.register(
            conversation_id=assistant_message.conversation_id,
            message_id=assistant_message.id,
            model=self.settings.openai_model,
            created_at=assistant_message.created_at,
            thinking_completed_at=None,
        )
        return assistant_message

    def _prepared_input_from_message(self, message: MessageRecord) -> PreparedInput:
        text_parts = [
            part.text.strip()
            for part in message.parts
            if part.type == "text" and part.text and part.text.strip()
        ]
        images = [
            PreparedImage(
                media_type=part.asset.media_type,
                upload_storage_path=part.asset.storage_path,
            )
            for part in message.parts
            if part.type == "image" and part.asset is not None
        ]
        return PreparedInput(
            text_parts=text_parts,
            images=images,
            preview_text=message.preview_text,
            title_text=message.preview_text,
        )

    async def _build_upstream_messages(
        self,
        messages: list[MessageRecord],
    ) -> list[dict[str, Any]]:
        upstream_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "assistant":
                if not message.text_content:
                    continue
                upstream_messages.append(
                    {"role": "assistant", "content": message.text_content}
                )
                continue

            text_segments: list[str] = []
            content_parts: list[dict[str, Any]] = []
            has_images = False
            for part in message.parts:
                if part.type == "text" and part.text:
                    text_segments.append(part.text)
                    content_parts.append({"type": "text", "text": part.text})
                    continue
                if part.type == "image" and part.asset is not None:
                    has_images = True
                    asset_bytes = await read_bytes(Path(part.asset.storage_path))
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
                upstream_messages.append(
                    {"role": "user", "content": "\n\n".join(text_segments)}
                )
        return upstream_messages

    async def _build_current_turn_message(
        self,
        prepared_input: PreparedInput,
    ) -> dict[str, Any]:
        content_parts: list[dict[str, Any]] = []
        for text in prepared_input.text_parts:
            content_parts.append({"type": "text", "text": text})

        if not prepared_input.images:
            return {"role": "user", "content": "\n\n".join(prepared_input.text_parts)}

        for image in prepared_input.images:
            image_bytes = (
                image.inline_bytes
                if image.inline_bytes is not None
                else await read_bytes(Path(image.upload_storage_path or ""))
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
        self,
        *,
        prepared_input: PreparedInput,
        message_id: str,
    ) -> tuple[list[NewMessagePart], list[Path]]:
        parts: list[NewMessagePart] = [
            NewMessagePart(type="text", text=text) for text in prepared_input.text_parts
        ]
        created_paths: list[Path] = []

        for image in prepared_input.images:
            asset_id = image.upload_id or uuid4().hex
            asset_path = self.repository.assets_dir / (
                f"{message_id}_{asset_id}{IMAGE_EXTENSION_BY_MEDIA_TYPE[image.media_type]}"
            )

            if image.inline_bytes is not None:
                await write_bytes(asset_path, image.inline_bytes)
            else:
                claimed_upload = await self.repository.pop_upload(image.upload_id or "")
                if claimed_upload is None or not Path(claimed_upload.storage_path).exists():
                    raise ChatPreStreamError(
                        status_code=422,
                        detail=PUBLIC_UPLOAD_NOT_FOUND_ERROR,
                    )
                await move_path(Path(claimed_upload.storage_path), asset_path)

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
