import httpx
from openai import AsyncOpenAI

from backend.app.core.settings import AppSettings


def build_openai_timeout(settings: AppSettings) -> httpx.Timeout:
    return httpx.Timeout(
        timeout=settings.openai_read_timeout_seconds,
        connect=settings.openai_connect_timeout_seconds,
        read=settings.openai_read_timeout_seconds,
        write=settings.openai_write_timeout_seconds,
        pool=settings.openai_connect_timeout_seconds,
    )


def build_health_timeout(settings: AppSettings) -> httpx.Timeout:
    return httpx.Timeout(settings.health_deep_timeout_seconds)


def create_openai_client(settings: AppSettings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=build_openai_timeout(settings),
    )
