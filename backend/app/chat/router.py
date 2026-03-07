"""Chat router for conversation, streaming, and asset endpoints."""

from pathlib import Path

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.chat.schemas import (
    CancelMessageResponse,
    ChatStreamEvent,
    ChatStreamRequest,
    ChatUploadResponse,
    ConversationDetail,
    ConversationSummary,
)
from backend.app.chat.service import (
    NDJSON_MEDIA_TYPE,
    STREAM_HEADERS,
    ChatPreStreamError,
    build_chat_error_response,
    cancel_message,
    delete_conversation,
    delete_upload,
    generate_chat_stream,
    get_asset_record,
    get_conversation_detail,
    get_upload_record,
    list_conversations,
    prepare_chat_stream,
    upload_chat_file,
)
from backend.app.core.api_errors import ApiErrorResponse, build_api_error_response

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
async def chat_stream(payload: ChatStreamRequest, request: Request) -> Response:
    try:
        prepared_stream = await prepare_chat_stream(request, payload)
    except ChatPreStreamError as exc:
        return build_chat_error_response(request, exc)

    request.state.is_streaming_response = True
    return StreamingResponse(
        generate_chat_stream(request, prepared_stream),
        media_type=NDJSON_MEDIA_TYPE,
        headers=STREAM_HEADERS,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(request: Request) -> list[ConversationSummary]:
    return await list_conversations(request)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_detail(
    conversation_id: str, request: Request
) -> ConversationDetail | Response:
    detail = await get_conversation_detail(request, conversation_id)
    if detail is None:
        return build_api_error_response(
            status_code=404,
            detail="Conversation not found.",
            request_id=getattr(request.state, "request_id", "-"),
        )
    return detail


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_delete(conversation_id: str, request: Request) -> Response:
    deleted = await delete_conversation(request, conversation_id)
    if not deleted:
        return build_api_error_response(
            status_code=404,
            detail="Conversation not found.",
            request_id=getattr(request.state, "request_id", "-"),
        )
    return Response(status_code=204)


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/cancel",
    response_model=CancelMessageResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def conversation_message_cancel(
    conversation_id: str,
    message_id: str,
    request: Request,
) -> CancelMessageResponse | Response:
    cancelled = await cancel_message(request, conversation_id, message_id)
    if cancelled is None:
        return build_api_error_response(
            status_code=404,
            detail="Assistant message not found.",
            request_id=getattr(request.state, "request_id", "-"),
    )
    return cancelled


@router.post(
    "/chat/uploads",
    response_model=ChatUploadResponse,
    responses={422: {"model": ApiErrorResponse}, 500: {"model": ApiErrorResponse}},
)
async def chat_upload(request: Request, file: UploadFile = File(...)):
    try:
        return await upload_chat_file(request, file)
    except ChatPreStreamError as exc:
        return build_chat_error_response(request, exc)


@router.get(
    "/chat/uploads/{upload_id}",
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_upload_asset(upload_id: str, request: Request):
    upload = await get_upload_record(request, upload_id)
    if upload is None or not Path(upload.storage_path).exists():
        return build_api_error_response(
            status_code=404,
            detail="Upload not found.",
            request_id=getattr(request.state, "request_id", "-"),
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
async def chat_upload_delete(upload_id: str, request: Request) -> Response:
    deleted = await delete_upload(request, upload_id)
    if not deleted:
        return build_api_error_response(
            status_code=404,
            detail="Upload not found.",
            request_id=getattr(request.state, "request_id", "-"),
        )
    return Response(status_code=204)


@router.get(
    "/chat/assets/{asset_id}",
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_asset(asset_id: str, request: Request):
    asset = await get_asset_record(request, asset_id)
    if asset is None or not Path(asset.storage_path).exists():
        return build_api_error_response(
            status_code=404,
            detail="Asset not found.",
            request_id=getattr(request.state, "request_id", "-"),
        )
    return FileResponse(
        asset.storage_path,
        media_type=asset.media_type,
        filename=f"{asset.id}{Path(asset.storage_path).suffix}",
    )
