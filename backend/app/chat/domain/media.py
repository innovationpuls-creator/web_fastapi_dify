from __future__ import annotations

import base64
import binascii

from backend.app.chat.domain.constants import PUBLIC_INVALID_IMAGE_ERROR
from backend.app.chat.domain.errors import ChatPreStreamError


def normalize_base64(data: str) -> bytes:
    payload = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ChatPreStreamError(
            status_code=422,
            detail=PUBLIC_INVALID_IMAGE_ERROR,
        ) from exc
