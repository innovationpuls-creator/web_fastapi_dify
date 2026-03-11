from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.app.chat.domain.text import has_complete_thinking_block


@dataclass(frozen=True)
class ActiveStreamSnapshot:
    conversation_id: str
    message_id: str
    text_content: str
    model: str | None
    created_at: str
    updated_at: str
    thinking_completed_at: str | None


@dataclass
class ActiveStreamState:
    conversation_id: str
    message_id: str
    model: str | None
    created_at: str
    updated_at: str
    thinking_completed_at: str | None = None
    text_content: str = ""
    cancel_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        if self.cancel_event is None:
            self.cancel_event = asyncio.Event()

    def snapshot(self) -> ActiveStreamSnapshot:
        return ActiveStreamSnapshot(
            conversation_id=self.conversation_id,
            message_id=self.message_id,
            text_content=self.text_content,
            model=self.model,
            created_at=self.created_at,
            updated_at=self.updated_at,
            thinking_completed_at=self.thinking_completed_at,
        )


class ChatCancellationRegistry:
    def __init__(self) -> None:
        self._streams: dict[str, ActiveStreamState] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        conversation_id: str,
        message_id: str,
        model: str | None,
        created_at: str,
        thinking_completed_at: str | None = None,
    ) -> None:
        async with self._lock:
            self._streams[message_id] = ActiveStreamState(
                conversation_id=conversation_id,
                message_id=message_id,
                model=model,
                created_at=created_at,
                updated_at=created_at,
                thinking_completed_at=thinking_completed_at,
            )

    async def append_text(
        self,
        message_id: str,
        delta: str,
        *,
        updated_at: str,
        thinking_completed_at: str | None = None,
    ) -> None:
        async with self._lock:
            state = self._streams.get(message_id)
            if state is None:
                return
            state.text_content += delta
            state.updated_at = updated_at
            if state.thinking_completed_at is None:
                if thinking_completed_at is not None:
                    state.thinking_completed_at = thinking_completed_at
                elif has_complete_thinking_block(state.text_content):
                    state.thinking_completed_at = updated_at

    async def request_cancel(
        self, *, conversation_id: str, message_id: str, updated_at: str
    ) -> ActiveStreamSnapshot | None:
        async with self._lock:
            state = self._streams.get(message_id)
            if state is None or state.conversation_id != conversation_id:
                return None
            state.updated_at = updated_at
            state.cancel_event.set()
            return state.snapshot()

    async def snapshot(self, message_id: str) -> ActiveStreamSnapshot | None:
        async with self._lock:
            state = self._streams.get(message_id)
            return state.snapshot() if state is not None else None

    async def cancel_event(self, message_id: str) -> asyncio.Event | None:
        async with self._lock:
            state = self._streams.get(message_id)
            return state.cancel_event if state is not None else None

    async def unregister(self, message_id: str) -> None:
        async with self._lock:
            self._streams.pop(message_id, None)
