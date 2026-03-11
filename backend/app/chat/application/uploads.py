from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import UploadFile

from backend.app.chat.application.presenters import upload_url
from backend.app.chat.domain.constants import (
    IMAGE_EXTENSION_BY_MEDIA_TYPE,
    PUBLIC_INVALID_IMAGE_ERROR,
    PUBLIC_UPLOAD_UNSUPPORTED_ERROR,
)
from backend.app.chat.domain.errors import ChatPreStreamError
from backend.app.chat.domain.text import expired_upload_cutoff, utc_now
from backend.app.chat.infrastructure.file_store import delete_paths, write_bytes
from backend.app.chat.infrastructure.persistence import ChatRepository
from backend.app.chat.schemas import ChatUploadResponse
from backend.app.core.settings import AppSettings


@dataclass(slots=True)
class UploadService:
    repository: ChatRepository
    settings: AppSettings

    async def purge_expired_uploads(self) -> None:
        expired_paths = await self.repository.delete_expired_uploads(
            expired_upload_cutoff(self.settings.chat_upload_ttl_seconds)
        )
        await delete_paths(expired_paths)

    async def upload_chat_file(self, file: UploadFile) -> ChatUploadResponse:
        await self.purge_expired_uploads()

        media_type = file.content_type or ""
        if media_type not in IMAGE_EXTENSION_BY_MEDIA_TYPE:
            raise ChatPreStreamError(
                status_code=422,
                detail=PUBLIC_UPLOAD_UNSUPPORTED_ERROR,
            )

        payload = await file.read()
        await file.close()
        if not payload:
            raise ChatPreStreamError(status_code=422, detail=PUBLIC_INVALID_IMAGE_ERROR)
        if len(payload) > self.settings.chat_max_image_bytes:
            raise ChatPreStreamError(
                status_code=422,
                detail=f"Image exceeds the {self.settings.chat_max_image_bytes} byte limit.",
            )

        upload_id = uuid4().hex
        upload_path = self.repository.uploads_dir / (
            f"{upload_id}{IMAGE_EXTENSION_BY_MEDIA_TYPE[media_type]}"
        )
        await write_bytes(upload_path, payload)

        record = await self.repository.create_upload(
            upload_id=upload_id,
            media_type=media_type,
            storage_path=str(upload_path),
            byte_size=len(payload),
            created_at=utc_now(),
        )
        return ChatUploadResponse(
            upload_id=record.id,
            url=upload_url(record.id),
            media_type=record.media_type,
            byte_size=record.byte_size,
            created_at=record.created_at,
        )

    async def delete_upload(self, upload_id: str) -> bool:
        deleted_path = await self.repository.delete_upload(upload_id)
        if deleted_path is None:
            return False
        await delete_paths([deleted_path])
        return True
