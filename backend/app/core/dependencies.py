from fastapi import Depends, Request

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.core.container import AppContainer, get_app_container
from backend.app.core.openai_client import OpenAIGateway
from backend.app.core.request_context import request_id
from backend.app.core.settings import AppSettings


def get_container(request: Request) -> AppContainer:
    return get_app_container(request)


def get_settings(container: AppContainer = Depends(get_container)) -> AppSettings:
    return container.settings


def get_chat_repository(
    container: AppContainer = Depends(get_container),
) -> ChatRepository:
    return container.chat_repository


def get_chat_cancellation_registry(
    container: AppContainer = Depends(get_container),
) -> ChatCancellationRegistry:
    return container.chat_cancellation_registry


def get_openai_gateway(
    container: AppContainer = Depends(get_container),
) -> OpenAIGateway:
    return container.openai_gateway


def get_request_id_value(request: Request) -> str:
    return request_id(request)
