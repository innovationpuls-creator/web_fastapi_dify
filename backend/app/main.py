import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.api.router import router as chat_router
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.core.container import AppContainer, set_app_container
from backend.app.core.logging import configure_logging
from backend.app.core.openai_client import create_openai_gateway
from backend.app.core.settings import AppSettings, get_settings
from backend.app.health.router import router as health_router
from backend.app.middleware.request_logging import register_request_logging_middleware

logger = logging.getLogger(__name__)


def build_app_container(settings: AppSettings) -> AppContainer:
    return AppContainer(
        settings=settings,
        chat_repository=ChatRepository(
            settings.chat_database_path,
            settings.chat_assets_dir,
            settings.chat_uploads_dir,
        ),
        chat_cancellation_registry=ChatCancellationRegistry(),
        openai_gateway=create_openai_gateway(settings),
    )


def create_app(
    container_factory: Callable[[AppSettings], AppContainer] | None = None,
) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    container_factory = container_factory or build_app_container

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = container_factory(settings)
        await container.initialize()
        set_app_container(app, container)
        logger.info(
            "application_started",
            extra={"feature": "startup", "model": settings.openai_model},
        )
        yield
        await container.close()
        logger.info(
            "application_stopped",
            extra={"feature": "shutdown", "model": settings.openai_model},
        )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_request_logging_middleware(app)
    app.include_router(chat_router)
    app.include_router(health_router)
    return app


app = create_app()
