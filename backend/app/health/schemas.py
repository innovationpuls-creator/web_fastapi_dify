"""Health schemas.

Inputs:
- `GET /health`: no body, only checks local service readiness.
- `GET /health/deep`: no body, also probes the upstream AI endpoint.

Outputs:
- `HealthResponse`: service-level status and config state.
- `DeepHealthResponse`: service-level status plus upstream model probe result.
"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    version: str
    config_loaded: bool = Field(
        description="True when typed settings loaded successfully at startup."
    )


class DeepHealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app_name: str
    version: str
    config_loaded: bool
    upstream_status: Literal["ok", "error"]
    model: str
    latency_ms: float | None = None
    error: str | None = None
