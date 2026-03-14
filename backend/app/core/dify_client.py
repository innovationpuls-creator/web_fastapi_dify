from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.core.settings import AppSettings


@dataclass(slots=True)
class DifyGateway:
    client: httpx.AsyncClient | None

    async def get_parameters(self) -> dict[str, object]:
        if self.client is None:
            raise RuntimeError("Dify chatflow is not configured.")

        response = await self.client.get("/parameters")
        response.raise_for_status()
        return response.json()

    async def create_chat_stream(
        self,
        *,
        query: str,
        user: str,
        inputs: dict[str, object],
    ) -> httpx.Response:
        if self.client is None:
            raise RuntimeError("Dify chatflow is not configured.")

        request = self.client.build_request(
            "POST",
            "/chat-messages",
            json={
                "inputs": inputs,
                "query": query,
                "response_mode": "streaming",
                "user": user,
            },
        )
        response = await self.client.send(request, stream=True)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            await response.aclose()
            raise
        return response

    async def stop_chat_message(self, *, task_id: str, user: str) -> None:
        if self.client is None:
            raise RuntimeError("Dify chatflow is not configured.")

        response = await self.client.post(
            f"/chat-messages/{task_id}/stop",
            json={"user": user},
        )
        response.raise_for_status()

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()


def create_dify_client(settings: AppSettings) -> httpx.AsyncClient | None:
    if not settings.dify_enabled:
        return None

    base_url = settings.dify_api_base_url.rstrip("/")
    timeout = httpx.Timeout(
        timeout=settings.dify_read_timeout_seconds,
        connect=settings.dify_connect_timeout_seconds,
        read=settings.dify_read_timeout_seconds,
        write=settings.dify_write_timeout_seconds,
        pool=settings.dify_connect_timeout_seconds,
    )
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        headers={
            "Authorization": f"Bearer {settings.dify_api_key}",
            "Accept": "text/event-stream",
        },
    )


def create_dify_gateway(settings: AppSettings) -> DifyGateway:
    return DifyGateway(client=create_dify_client(settings))
