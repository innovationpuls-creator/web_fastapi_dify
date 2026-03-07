from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ApiErrorResponse(BaseModel):
    detail: str
    request_id: str
    upstream_error: str | None = None


def build_api_error_response(
    *,
    status_code: int,
    detail: str,
    request_id: str,
    upstream_error: str | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        detail=detail,
        request_id=request_id,
        upstream_error=upstream_error,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())
