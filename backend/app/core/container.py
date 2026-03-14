from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.domain.text import expired_upload_cutoff
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.chat.infrastructure.file_store import delete_paths
from backend.app.core.dify_client import DifyGateway
from backend.app.core.openai_client import OpenAIGateway
from backend.app.core.settings import AppSettings


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    chat_repository: ChatRepository
    chat_cancellation_registry: ChatCancellationRegistry
    openai_gateway: OpenAIGateway
    dify_gateway: DifyGateway

    async def initialize(self) -> None:
        await self.chat_repository.initialize()
        expired_paths = await self.chat_repository.delete_expired_uploads(
            expired_upload_cutoff(self.settings.chat_upload_ttl_seconds)
        )
        await delete_paths(expired_paths)

    async def close(self) -> None:
        await self.dify_gateway.close()
        await self.openai_gateway.close()


def set_app_container(app: FastAPI, container: AppContainer) -> None:
    app.state.container = container


def get_app_container(request: Request) -> AppContainer:
    return request.app.state.container
