"""Health router.

Inputs:
- `GET /health` without a body.
- `GET /health/deep` without a body.

Outputs:
- Pydantic JSON responses for shallow and deep health checks.
"""

from fastapi import APIRouter, Depends, Request, Response

from backend.app.core.dependencies import get_openai_gateway, get_settings
from backend.app.health.schemas import DeepHealthResponse, HealthResponse
from backend.app.health.service import HealthService

router = APIRouter(tags=["health"])


def get_health_service(
    settings=Depends(get_settings),
    openai_gateway=Depends(get_openai_gateway),
) -> HealthService:
    return HealthService(settings=settings, openai_gateway=openai_gateway)


@router.get("/health", response_model=HealthResponse)
async def health(
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    return health_service.get_liveness_health()


@router.get(
    "/health/deep",
    response_model=DeepHealthResponse,
    responses={503: {"model": DeepHealthResponse}},
)
async def health_deep(
    request: Request,
    response: Response,
    health_service: HealthService = Depends(get_health_service),
) -> DeepHealthResponse:
    result, status_code = await health_service.get_deep_health(request)
    response.status_code = status_code
    return result
