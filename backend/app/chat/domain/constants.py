from __future__ import annotations

import re

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

THINK_BLOCK_PATTERN = re.compile(
    r"<think\b[^>]*>.*?(?:</think\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)

COMPLETE_THINK_BLOCK_PATTERN = re.compile(
    r"<think\b[^>]*>.*?</think\s*>",
    re.IGNORECASE | re.DOTALL,
)
