import logging
import time
import uuid

from fastapi import FastAPI, Request

from backend.app.core.api_errors import build_api_error_response
from backend.app.core.logging import reset_request_id, set_request_id

logger = logging.getLogger(__name__)


def _feature_from_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[0] if parts else "root"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def register_request_logging_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = set_request_id(request_id)
        start_time = time.perf_counter()
        feature = _feature_from_path(request.url.path)
        client_ip = _client_ip(request)
        request.state.request_id = request_id
        request.state.is_streaming_response = False

        logger.info(
            "request_started",
            extra={
                "request_id": request_id,
                "feature": feature,
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
            },
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "feature": feature,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                },
            )
            response = build_api_error_response(
                status_code=500,
                detail="Internal Server Error",
                request_id=request_id,
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_extra = {
            "request_id": request_id,
            "feature": feature,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
        }
        if getattr(request.state, "is_streaming_response", False):
            logger.info("stream_response_started", extra=log_extra)
        else:
            logger.info("request_completed", extra=log_extra)
        response.headers["X-Request-ID"] = request_id
        reset_request_id(token)
        return response
