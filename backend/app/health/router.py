"""Health router.

Inputs:
- `GET /health` without a body.
- `GET /health/deep` without a body.

Outputs:
- Pydantic JSON responses for shallow and deep health checks.
"""

from fastapi import APIRouter, Request, Response

from backend.app.health.schemas import DeepHealthResponse, HealthResponse
from backend.app.health.service import get_deep_health, get_liveness_health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return get_liveness_health(request)


@router.get(
    "/health/deep",
    response_model=DeepHealthResponse,
    responses={503: {"model": DeepHealthResponse}},
)
async def health_deep(request: Request, response: Response) -> DeepHealthResponse:
    result, status_code = await get_deep_health(request)
    response.status_code = status_code
    return result
