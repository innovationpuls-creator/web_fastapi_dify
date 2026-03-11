from __future__ import annotations

from typing import Any

from fastapi import Request


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def build_log_context(
    request: Request,
    *,
    feature: str,
    model: str | None = None,
    message_count: int | str = "-",
    duration_ms: float | str = "-",
    status_code: int | str = "-",
) -> dict[str, Any]:
    return {
        "request_id": request_id(request),
        "feature": feature,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "client_ip": client_ip(request),
        "model": model or "-",
        "message_count": message_count,
    }
