from fastapi import Depends

from backend.app.chat.application.conversations import ConversationService
from backend.app.chat.application.streaming import ChatStreamService
from backend.app.chat.application.uploads import UploadService
from backend.app.core.dependencies import (
    get_chat_cancellation_registry,
    get_chat_repository,
    get_dify_gateway,
    get_openai_gateway,
    get_settings,
)


def get_conversation_service(
    repository=Depends(get_chat_repository),
    cancellation_registry=Depends(get_chat_cancellation_registry),
) -> ConversationService:
    return ConversationService(
        repository=repository,
        cancellation_registry=cancellation_registry,
    )


def get_upload_service(
    repository=Depends(get_chat_repository),
    settings=Depends(get_settings),
) -> UploadService:
    return UploadService(repository=repository, settings=settings)


def get_stream_service(
    repository=Depends(get_chat_repository),
    cancellation_registry=Depends(get_chat_cancellation_registry),
    openai_gateway=Depends(get_openai_gateway),
    dify_gateway=Depends(get_dify_gateway),
    settings=Depends(get_settings),
) -> ChatStreamService:
    return ChatStreamService(
        repository=repository,
        cancellation_registry=cancellation_registry,
        openai_gateway=openai_gateway,
        dify_gateway=dify_gateway,
        settings=settings,
    )
