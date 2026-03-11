from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from backend.app.core.settings import AppSettings


@dataclass(slots=True)
class OpenAIGateway:
    client: AsyncOpenAI

    async def create_chat_stream(self, request_args: dict[str, Any]) -> Any:
        return await self.client.chat.completions.create(**request_args)

    async def probe_health(self, *, model: str, timeout: httpx.Timeout) -> None:
        await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=1,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self.client.close()


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


def create_openai_gateway(settings: AppSettings) -> OpenAIGateway:
    return OpenAIGateway(client=create_openai_client(settings))
