import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.repository import ChatRepository
from backend.app.chat.router import router as chat_router
from backend.app.core.logging import configure_logging
from backend.app.core.openai_client import create_openai_client
from backend.app.core.settings import get_settings
from backend.app.health.router import router as health_router
from backend.app.middleware.request_logging import register_request_logging_middleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.chat_repository = ChatRepository(
            settings.chat_database_path,
            settings.chat_assets_dir,
            settings.chat_uploads_dir,
        )
        await app.state.chat_repository.initialize()
        expired_paths = await app.state.chat_repository.delete_expired_uploads(
            (
                datetime.now(UTC) - timedelta(seconds=settings.chat_upload_ttl_seconds)
            ).isoformat(timespec="seconds")
        )
        if expired_paths:
            for path in expired_paths:
                await asyncio.to_thread(Path(path).unlink, missing_ok=True)
        app.state.chat_cancellation_registry = ChatCancellationRegistry()
        app.state.openai_client = create_openai_client(settings)
        logger.info(
            "application_started",
            extra={"feature": "startup", "model": settings.openai_model},
        )
        yield
        await app.state.openai_client.close()
        logger.info(
            "application_stopped",
            extra={"feature": "shutdown", "model": settings.openai_model},
        )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
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
