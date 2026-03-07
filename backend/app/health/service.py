"""Health service.

Inputs:
- `Request`: provides access to app settings, shared OpenAI client, and request metadata.

Outputs:
- `HealthResponse`: lightweight liveness payload.
- `tuple[DeepHealthResponse, int]`: upstream-aware health result plus the HTTP status code to return.
"""

import logging
import time
from typing import Any

from fastapi import Request

from backend.app.core.openai_client import build_health_timeout
from backend.app.core.settings import AppSettings
from backend.app.health.schemas import DeepHealthResponse, HealthResponse

logger = logging.getLogger(__name__)
PUBLIC_HEALTH_ERROR = "Upstream health probe failed."


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _log_context(
    request: Request,
    model: str,
    duration_ms: float | str = "-",
    status_code: int | str = "-",
) -> dict[str, Any]:
    return {
        "request_id": getattr(request.state, "request_id", "-"),
        "feature": "health",
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "client_ip": _client_ip(request),
        "model": model,
        "message_count": 1,
    }


def get_liveness_health(request: Request) -> HealthResponse:
    settings: AppSettings = request.app.state.settings
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        config_loaded=True,
    )


async def get_deep_health(request: Request) -> tuple[DeepHealthResponse, int]:
    settings: AppSettings = request.app.state.settings
    client = request.app.state.openai_client
    start_time = time.perf_counter()

    try:
        await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=1,
            timeout=build_health_timeout(settings),
        )
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception(
            "health_deep_failed",
            extra=_log_context(
                request,
                settings.openai_model,
                duration_ms=duration_ms,
                status_code=503,
            ),
        )
        return (
            DeepHealthResponse(
                status="degraded",
                app_name=settings.app_name,
                version=settings.app_version,
                config_loaded=True,
                upstream_status="error",
                model=settings.openai_model,
                latency_ms=duration_ms,
                error=PUBLIC_HEALTH_ERROR,
            ),
            503,
        )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(
        "health_deep_ok",
        extra=_log_context(
            request,
            settings.openai_model,
            duration_ms=duration_ms,
            status_code=200,
        ),
    )
    return (
        DeepHealthResponse(
            status="ok",
            app_name=settings.app_name,
            version=settings.app_version,
            config_loaded=True,
            upstream_status="ok",
            model=settings.openai_model,
            latency_ms=duration_ms,
        ),
        200,
    )
