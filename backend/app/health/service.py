"""Health service."""

from dataclasses import dataclass
import logging
import time

from fastapi import Request

from backend.app.core.openai_client import OpenAIGateway, build_health_timeout
from backend.app.core.request_context import build_log_context
from backend.app.core.settings import AppSettings
from backend.app.health.schemas import DeepHealthResponse, HealthResponse

logger = logging.getLogger(__name__)
PUBLIC_HEALTH_ERROR = "Upstream health probe failed."


@dataclass(slots=True)
class HealthService:
    settings: AppSettings
    openai_gateway: OpenAIGateway

    def get_liveness_health(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            app_name=self.settings.app_name,
            version=self.settings.app_version,
            config_loaded=True,
            dify_enabled=self.settings.dify_enabled,
        )

    async def get_deep_health(self, request: Request) -> tuple[DeepHealthResponse, int]:
        start_time = time.perf_counter()

        try:
            await self.openai_gateway.probe_health(
                model=self.settings.openai_model,
                timeout=build_health_timeout(self.settings),
            )
        except Exception:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "health_deep_failed",
                extra=build_log_context(
                    request,
                    feature="health",
                    model=self.settings.openai_model,
                    message_count=1,
                    duration_ms=duration_ms,
                    status_code=503,
                ),
            )
            return (
                DeepHealthResponse(
                    status="degraded",
                    app_name=self.settings.app_name,
                    version=self.settings.app_version,
                    config_loaded=True,
                    upstream_status="error",
                    model=self.settings.openai_model,
                    latency_ms=duration_ms,
                    error=PUBLIC_HEALTH_ERROR,
                ),
                503,
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "health_deep_ok",
            extra=build_log_context(
                request,
                feature="health",
                model=self.settings.openai_model,
                message_count=1,
                duration_ms=duration_ms,
                status_code=200,
            ),
        )
        return (
            DeepHealthResponse(
                status="ok",
                app_name=self.settings.app_name,
                version=self.settings.app_version,
                config_loaded=True,
                upstream_status="ok",
                model=self.settings.openai_model,
                latency_ms=duration_ms,
            ),
            200,
        )
