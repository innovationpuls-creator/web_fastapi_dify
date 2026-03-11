from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

from backend.app.chat.domain.constants import (
    COMPLETE_THINK_BLOCK_PATTERN,
    THINK_BLOCK_PATTERN,
)
from backend.app.chat.schemas import ImageInputPart, InputPart, TextInputPart


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def timestamp_title() -> str:
    return datetime.now(UTC).strftime("Conversation %Y-%m-%d %H:%M UTC")


def strip_visible_preview(value: str, *, fallback: str) -> str:
    collapsed = " ".join(value.split())
    if not collapsed:
        return fallback
    return f"{collapsed[:117]}..." if len(collapsed) > 120 else collapsed


def derive_title(parts: list[InputPart]) -> str:
    for part in parts:
        if isinstance(part, TextInputPart):
            cleaned = " ".join(part.text.split())
            if cleaned:
                return cleaned[:40]
    return timestamp_title()


def preview_from_input_parts(parts: list[InputPart]) -> str:
    texts = [
        " ".join(part.text.split())
        for part in parts
        if isinstance(part, TextInputPart) and part.text.strip()
    ]
    if texts:
        return strip_visible_preview(" ".join(texts), fallback="New message")
    image_count = sum(1 for part in parts if isinstance(part, ImageInputPart))
    return "[Image]" if image_count == 1 else f"[{image_count} images]"


def strip_reasoning_blocks(value: str) -> str:
    stripped = THINK_BLOCK_PATTERN.sub("", value)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def has_complete_thinking_block(value: str) -> bool:
    return COMPLETE_THINK_BLOCK_PATTERN.search(value) is not None


def preview_from_text(value: str, *, fallback: str) -> str:
    visible_text = strip_reasoning_blocks(value)
    return strip_visible_preview(visible_text, fallback=fallback)


def expired_upload_cutoff(ttl_seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=ttl_seconds)).isoformat(
        timespec="seconds"
    )
