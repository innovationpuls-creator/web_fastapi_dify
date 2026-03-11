"""Chat router for conversation, streaming, and asset endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.chat.api.dependencies import (
    get_conversation_service,
    get_stream_service,
    get_upload_service,
)
from backend.app.chat.application.conversations import ConversationService
from backend.app.chat.application.presenters import build_chat_error_response
from backend.app.chat.application.streaming import ChatStreamService
from backend.app.chat.application.uploads import UploadService
from backend.app.chat.domain.constants import NDJSON_MEDIA_TYPE, STREAM_HEADERS
from backend.app.chat.domain.errors import ChatPreStreamError
from backend.app.chat.schemas import (
    CancelMessageResponse,
    ChatStreamEvent,
    ChatStreamRequest,
    ChatUploadResponse,
    ConversationDetail,
    ConversationSummary,
)
from backend.app.core.api_errors import ApiErrorResponse, build_api_error_response
from backend.app.core.dependencies import get_request_id_value

router = APIRouter(tags=["chat"])


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                NDJSON_MEDIA_TYPE: {"schema": ChatStreamEvent.model_json_schema()}
            },
            "description": "NDJSON stream. Each line is a ChatStreamEvent JSON object.",
        },
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        500: {"model": ApiErrorResponse},
        502: {"model": ApiErrorResponse},
    },
)
async def chat_stream(
    payload: ChatStreamRequest,
    request: Request,
    stream_service: ChatStreamService = Depends(get_stream_service),
    request_id: str = Depends(get_request_id_value),
) -> Response:
    try:
        prepared_stream = await stream_service.prepare_chat_stream(request, payload)
    except ChatPreStreamError as exc:
        return build_chat_error_response(request_id=request_id, exc=exc)

    request.state.is_streaming_response = True
    return StreamingResponse(
        stream_service.generate_chat_stream(request, prepared_stream),
        media_type=NDJSON_MEDIA_TYPE,
        headers=STREAM_HEADERS,
    )


@router.get("/chat/conversations", response_model=list[ConversationSummary])
async def conversations(
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationSummary]:
    return await conversation_service.list_conversations()


@router.get(
    "/chat/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_detail(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    request_id: str = Depends(get_request_id_value),
) -> ConversationDetail | Response:
    detail = await conversation_service.get_conversation_detail(conversation_id)
    if detail is None:
        return build_api_error_response(
            status_code=404,
            detail="Conversation not found.",
            request_id=request_id,
        )
    return detail


@router.delete(
    "/chat/conversations/{conversation_id}",
    status_code=204,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_delete(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    request_id: str = Depends(get_request_id_value),
) -> Response:
    deleted = await conversation_service.delete_conversation(conversation_id)
    if not deleted:
        return build_api_error_response(
            status_code=404,
            detail="Conversation not found.",
            request_id=request_id,
        )
    return Response(status_code=204)


@router.post(
    "/chat/conversations/{conversation_id}/messages/{message_id}/cancel",
    response_model=CancelMessageResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_message_cancel(
    conversation_id: str,
    message_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    request_id: str = Depends(get_request_id_value),
) -> CancelMessageResponse | Response:
    cancelled = await conversation_service.cancel_message(conversation_id, message_id)
    if cancelled is None:
        return build_api_error_response(
            status_code=404,
            detail="Assistant message not found.",
            request_id=request_id,
        )
    return cancelled


@router.post(
    "/chat/uploads",
    response_model=ChatUploadResponse,
    responses={422: {"model": ApiErrorResponse}, 500: {"model": ApiErrorResponse}},
)
async def chat_upload(
    file: UploadFile = File(...),
    upload_service: UploadService = Depends(get_upload_service),
    request_id: str = Depends(get_request_id_value),
):
    try:
        return await upload_service.upload_chat_file(file)
    except ChatPreStreamError as exc:
        return build_chat_error_response(request_id=request_id, exc=exc)


@router.get(
    "/chat/uploads/{upload_id}",
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_upload_asset(
    upload_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    request_id: str = Depends(get_request_id_value),
):
    upload = await conversation_service.get_upload_record(upload_id)
    if upload is None:
        return build_api_error_response(
            status_code=404,
            detail="Upload not found.",
            request_id=request_id,
        )
    return FileResponse(
        upload.storage_path,
        media_type=upload.media_type,
        filename=f"{upload.id}{Path(upload.storage_path).suffix}",
    )


@router.delete(
    "/chat/uploads/{upload_id}",
    status_code=204,
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_upload_delete(
    upload_id: str,
    upload_service: UploadService = Depends(get_upload_service),
    request_id: str = Depends(get_request_id_value),
) -> Response:
    deleted = await upload_service.delete_upload(upload_id)
    if not deleted:
        return build_api_error_response(
            status_code=404,
            detail="Upload not found.",
            request_id=request_id,
        )
    return Response(status_code=204)


@router.get(
    "/chat/assets/{asset_id}",
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_asset(
    asset_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    request_id: str = Depends(get_request_id_value),
):
    asset = await conversation_service.get_asset_record(asset_id)
    if asset is None:
        return build_api_error_response(
            status_code=404,
            detail="Asset not found.",
            request_id=request_id,
        )
    return FileResponse(
        asset.storage_path,
        media_type=asset.media_type,
        filename=f"{asset.id}{Path(asset.storage_path).suffix}",
    )
