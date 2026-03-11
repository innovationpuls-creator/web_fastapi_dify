from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.core.openai_client import OpenAIGateway
from backend.app.core.settings import AppSettings


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    chat_repository: ChatRepository
    chat_cancellation_registry: ChatCancellationRegistry
    openai_gateway: OpenAIGateway

    async def initialize(self) -> None:
        await self.chat_repository.initialize()

    async def close(self) -> None:
        await self.openai_gateway.close()


def set_app_container(app: FastAPI, container: AppContainer) -> None:
    app.state.container = container


def get_app_container(request: Request) -> AppContainer:
    return request.app.state.container
