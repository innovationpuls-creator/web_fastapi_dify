from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from backend.app.chat.cancellation import ChatCancellationRegistry
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.core.container import AppContainer
from backend.app.core.dify_client import DifyGateway
from backend.app.core.settings import AppSettings


class _DummyGateway:
    async def close(self) -> None:
        return None


class AppContainerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base_path = Path("backend/tests/.tmp_container")
        shutil.rmtree(self.base_path, ignore_errors=True)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.repository = ChatRepository(
            self.base_path / "chat.sqlite3",
            self.base_path / "assets",
            self.base_path / "uploads",
        )
        self.settings = AppSettings(
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1234/v1",
            openai_model="test-model",
            chat_database_path=self.base_path / "chat.sqlite3",
            chat_assets_dir=self.base_path / "assets",
            chat_uploads_dir=self.base_path / "uploads",
            chat_upload_ttl_seconds=60,
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.base_path, ignore_errors=True)

    async def test_initialize_purges_expired_uploads(self) -> None:
        await self.repository.initialize()
        expired_path = self.base_path / "uploads" / "expired.png"
        fresh_path = self.base_path / "uploads" / "fresh.png"
        expired_path.parent.mkdir(parents=True, exist_ok=True)
        expired_path.write_bytes(b"expired")
        fresh_path.write_bytes(b"fresh")

        await self.repository.create_upload(
            upload_id="expired-upload",
            media_type="image/png",
            storage_path=str(expired_path),
            byte_size=len(b"expired"),
            created_at="2026-03-01T00:00:00+00:00",
        )
        await self.repository.create_upload(
            upload_id="fresh-upload",
            media_type="image/png",
            storage_path=str(fresh_path),
            byte_size=len(b"fresh"),
            created_at="2099-03-01T00:00:00+00:00",
        )

        container = AppContainer(
            settings=self.settings,
            chat_repository=self.repository,
            chat_cancellation_registry=ChatCancellationRegistry(),
            openai_gateway=_DummyGateway(),
            dify_gateway=DifyGateway(client=None),
        )

        await container.initialize()

        self.assertIsNone(await self.repository.get_upload("expired-upload"))
        self.assertFalse(expired_path.exists())
        self.assertIsNotNone(await self.repository.get_upload("fresh-upload"))
        self.assertTrue(fresh_path.exists())
