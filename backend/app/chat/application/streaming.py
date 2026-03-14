from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import Request
import httpx
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
    PUBLIC_DIFY_MODEL,
    PUBLIC_DIFY_NOT_CONFIGURED_ERROR,
    PUBLIC_DIFY_PARAMETERS_ERROR,
    PUBLIC_DIFY_TEXT_ONLY_ERROR,
    PUBLIC_DIFY_TIMEOUT_ERROR,
    PUBLIC_DIFY_UPSTREAM_ERROR,
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
from backend.app.core.dify_client import DifyGateway
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
    dify_gateway: DifyGateway
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
        dify_inputs: dict[str, object] = {}
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
            if payload.provider == "dify":
                self._validate_dify_input(prepared_input)
                dify_inputs = await self._resolve_dify_inputs()
        except ChatPreStreamError:
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise

        model_name = (
            PUBLIC_DIFY_MODEL if payload.provider == "dify" else self.settings.openai_model
        )

        logger.info(
            "chat_stream_started",
            extra=build_log_context(
                request,
                feature="chat",
                model=model_name,
                message_count=0,
            ),
        )

        stream: Any
        message_count = 1
        try:
            if payload.provider == "dify":
                stream = await self._create_dify_stream(
                    conversation.id,
                    prepared_input,
                    inputs=dify_inputs,
                )
            else:
                history = await self.repository.list_messages(conversation.id)
                upstream_messages = await self._build_upstream_messages(history)
                upstream_messages.append(await self._build_current_turn_message(prepared_input))
                message_count = len(upstream_messages)
                stream = await self.openai_gateway.create_chat_stream(
                    build_chat_request_args(payload, self.settings, upstream_messages)
                )
        except RuntimeError as exc:
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(
                status_code=503,
                detail=PUBLIC_DIFY_NOT_CONFIGURED_ERROR,
            ) from exc
        except httpx.ReadTimeout as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_upstream_timeout",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=model_name,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    status_code=504,
                ),
            )
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(
                status_code=504,
                detail=(
                    PUBLIC_DIFY_TIMEOUT_ERROR
                    if payload.provider == "dify"
                    else "Upstream chat stream timed out."
                ),
                upstream_error=(
                    PUBLIC_DIFY_TIMEOUT_ERROR
                    if payload.provider == "dify"
                    else PUBLIC_UPSTREAM_ERROR
                ),
            ) from exc
        except httpx.HTTPStatusError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_upstream_http_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=model_name,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    status_code=502,
                ),
            )
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(
                status_code=502,
                detail=(
                    _extract_dify_http_error_message(exc)
                    if payload.provider == "dify"
                    else "Upstream chat stream could not be established."
                ),
                upstream_error=(
                    PUBLIC_DIFY_UPSTREAM_ERROR
                    if payload.provider == "dify"
                    else PUBLIC_UPSTREAM_ERROR
                ),
            ) from exc
        except (OpenAIError, httpx.HTTPError) as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_upstream_error",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=model_name,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    status_code=502,
                ),
            )
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(
                status_code=502,
                detail=(
                    PUBLIC_DIFY_UPSTREAM_ERROR
                    if payload.provider == "dify"
                    else "Upstream chat stream could not be established."
                ),
                upstream_error=(
                    PUBLIC_DIFY_UPSTREAM_ERROR
                    if payload.provider == "dify"
                    else PUBLIC_UPSTREAM_ERROR
                ),
            ) from exc
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "chat_stream_prepare_failed",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=model_name,
                    message_count=message_count,
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
                model=model_name,
            )
        except ChatPreStreamError:
            await _close_upstream_stream(stream)
            await delete_paths(created_asset_paths)
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise
        except Exception as exc:
            await _close_upstream_stream(stream)
            await delete_paths(created_asset_paths)
            if conversation_created:
                await self.repository.delete_conversation(conversation.id)
            raise ChatPreStreamError(status_code=500, detail="Internal server error.") from exc

        await self.cancellation_registry.register(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            model=model_name,
            created_at=assistant_message.created_at,
            thinking_completed_at=assistant_message.thinking_completed_at,
        )
        refreshed_conversation = await self.repository.get_conversation(conversation.id)
        return PreparedChatStream(
            stream=stream,
            provider=payload.provider,
            start_time=start_time,
            message_count=message_count,
            model=model_name,
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
            provider="openai",
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
            provider="openai",
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
        if prepared_stream.provider == "dify":
            async for payload in self._generate_dify_chat_stream(request, prepared_stream):
                yield payload
            return

        async for payload in self._generate_openai_chat_stream(request, prepared_stream):
            yield payload

    async def _generate_openai_chat_stream(
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
            await _close_upstream_stream(stream)

    async def _generate_dify_chat_stream(
        self,
        request: Request,
        prepared_stream: PreparedChatStream,
    ) -> AsyncGenerator[bytes, None]:
        full_content_parts: list[str] = []
        finish_reason: str | None = None
        thinking_completed_at = prepared_stream.assistant_message.thinking_completed_at
        stream: httpx.Response = prepared_stream.stream
        start_time = prepared_stream.start_time
        chunk_count = 0
        first_chunk_logged = False
        task_id: str | None = None
        dify_user = _build_dify_user(prepared_stream.conversation.id)
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

        async def stop_remote_if_possible() -> None:
            if task_id is None:
                return
            with suppress(httpx.HTTPError):
                await self.dify_gateway.stop_chat_message(task_id=task_id, user=dify_user)

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
            async for event_payload in _iter_sse_json_events(stream):
                if task_id is None:
                    task_id = _extract_dify_task_id(event_payload)

                if cancel_event.is_set():
                    await stop_remote_if_possible()
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

                if await request.is_disconnected():
                    if cancel_event.is_set():
                        await stop_remote_if_possible()
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

                event_name = str(event_payload.get("event") or "").lower()
                if event_name == "error":
                    raise RuntimeError(_extract_dify_error(event_payload))
                if event_name in {"message_end", "workflow_finished"}:
                    finish_reason = "stop"

                delta = _extract_dify_delta(event_payload)
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

            if cancel_event.is_set():
                await stop_remote_if_possible()
                await finish_as_cancelled()
                return

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            final_text = "".join(full_content_parts)
            updated_message = await self.repository.update_message(
                message_id=prepared_stream.assistant_message.id,
                status="completed",
                preview_text=preview_from_text(final_text, fallback="Assistant reply"),
                text_content=final_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                finish_reason=finish_reason or "stop",
                error=None,
                thinking_completed_at=thinking_completed_at,
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
                        finish_reason=finish_reason or "stop",
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
        except httpx.ReadTimeout:
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
                error=PUBLIC_DIFY_TIMEOUT_ERROR,
                thinking_completed_at=thinking_completed_at,
            )
            logger.exception(
                "chat_stream_upstream_timeout",
                extra=build_log_context(
                    request,
                    feature="chat",
                    model=prepared_stream.model,
                    message_count=prepared_stream.message_count,
                    duration_ms=duration_ms,
                    status_code=504,
                ),
            )
            if not await request.is_disconnected():
                yield serialize_event(
                    ChatStreamEvent(
                        event="error",
                        model=prepared_stream.model,
                        conversation_id=prepared_stream.conversation.id,
                        assistant_message_id=prepared_stream.assistant_message.id,
                        error=PUBLIC_DIFY_TIMEOUT_ERROR,
                    )
                )
        except httpx.HTTPError:
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
                error=PUBLIC_DIFY_UPSTREAM_ERROR,
                thinking_completed_at=thinking_completed_at,
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
                        error=PUBLIC_DIFY_UPSTREAM_ERROR,
                    )
                )
        except Exception as exc:
            if cancel_event.is_set():
                await finish_as_cancelled()
                return
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            partial_text = "".join(full_content_parts)
            error_detail = str(exc).strip() or "Internal server error."
            await self.repository.update_message(
                message_id=prepared_stream.assistant_message.id,
                status="failed",
                preview_text=preview_from_text(partial_text, fallback="Generation failed"),
                text_content=partial_text,
                updated_at=utc_now(),
                model=prepared_stream.model,
                finish_reason=finish_reason,
                error=error_detail,
                thinking_completed_at=thinking_completed_at,
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
                        error=error_detail,
                    )
                )
        finally:
            await self.cancellation_registry.unregister(prepared_stream.assistant_message.id)
            await _close_upstream_stream(stream)

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

    def _validate_dify_input(self, prepared_input: PreparedInput) -> None:
        if prepared_input.images:
            raise ChatPreStreamError(
                status_code=422,
                detail=PUBLIC_DIFY_TEXT_ONLY_ERROR,
            )

    async def _resolve_dify_inputs(self) -> dict[str, object]:
        parameters = await self.dify_gateway.get_parameters()
        form_fields = _extract_dify_form_fields(parameters)
        if not form_fields:
            return {}

        if any(
            field.get("required") is True and _extract_dify_form_variable(field) is None
            for field in form_fields
        ):
            raise ChatPreStreamError(
                status_code=503,
                detail=PUBLIC_DIFY_PARAMETERS_ERROR,
            )

        required_variables = [
            variable
            for variable in (
                _extract_dify_form_variable(field)
                for field in form_fields
                if field.get("required") is True
            )
            if variable is not None
        ]
        supported_inputs = self.settings.dify_default_inputs
        unsupported_required = sorted(
            variable for variable in required_variables if variable not in supported_inputs
        )
        if unsupported_required:
            raise ChatPreStreamError(
                status_code=503,
                detail=_build_dify_required_inputs_error(unsupported_required),
            )

        available_variables = {
            variable
            for variable in (
                _extract_dify_form_variable(field) for field in form_fields
            )
            if variable is not None
        }
        return {
            variable: value
            for variable, value in supported_inputs.items()
            if variable in available_variables
        }

    async def _create_dify_stream(
        self,
        conversation_id: str,
        prepared_input: PreparedInput,
        *,
        inputs: dict[str, object],
    ) -> httpx.Response:
        return await self.dify_gateway.create_chat_stream(
            query="\n\n".join(prepared_input.text_parts),
            user=_build_dify_user(conversation_id),
            inputs=inputs,
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


def _build_dify_user(conversation_id: str) -> str:
    return f"conversation:{conversation_id}"


async def _iter_sse_json_events(stream: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    event_name = ""
    data_lines: list[str] = []

    async for raw_line in stream.aiter_lines():
        line = raw_line.strip()
        if not line:
            payload = _build_sse_payload(event_name, data_lines)
            if payload is not None:
                yield payload
            event_name = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    payload = _build_sse_payload(event_name, data_lines)
    if payload is not None:
        yield payload


def _build_sse_payload(event_name: str, data_lines: list[str]) -> dict[str, Any] | None:
    if not data_lines:
        return None

    raw_data = "\n".join(data_lines).strip()
    if not raw_data or raw_data == "[DONE]":
        return None

    payload = json.loads(raw_data)
    if isinstance(payload, dict):
        if event_name and "event" not in payload:
            payload["event"] = event_name
        return payload
    return None


def _extract_dify_task_id(payload: dict[str, Any]) -> str | None:
    task_id = payload.get("task_id")
    if isinstance(task_id, str) and task_id:
        return task_id
    return None


def _extract_dify_delta(payload: dict[str, Any]) -> str:
    for key in ("answer", "delta", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_dify_form_fields(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_form = payload.get("user_input_form")
    if isinstance(raw_form, dict):
        raw_items: list[object] = [raw_form]
    elif isinstance(raw_form, list):
        raw_items = raw_form
    else:
        return []

    form_fields: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        for input_type, config in raw_item.items():
            if not isinstance(config, dict):
                continue
            field = dict(config)
            field["input_type"] = input_type
            form_fields.append(field)
            break
    return form_fields


def _extract_dify_form_variable(field: dict[str, Any]) -> str | None:
    variable = field.get("variable")
    if isinstance(variable, str) and variable.strip():
        return variable.strip()
    return None


def _build_dify_required_inputs_error(variables: list[str]) -> str:
    suffix = ", ".join(variables)
    return f"{PUBLIC_DIFY_PARAMETERS_ERROR} Missing defaults for: {suffix}."


def _extract_dify_error(payload: dict[str, Any]) -> str:
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return PUBLIC_DIFY_UPSTREAM_ERROR


def _extract_dify_http_error_message(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    with suppress(ValueError):
        payload = response.json()
        if isinstance(payload, dict):
            return _extract_dify_error(payload)

    text = response.text.strip()
    if text:
        return text
    return PUBLIC_DIFY_UPSTREAM_ERROR


async def _close_upstream_stream(stream: Any) -> None:
    close = getattr(stream, "aclose", None)
    if callable(close):
        await close()
        return

    close = getattr(stream, "close", None)
    if callable(close):
        await close()


async def _cancel_pending_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
