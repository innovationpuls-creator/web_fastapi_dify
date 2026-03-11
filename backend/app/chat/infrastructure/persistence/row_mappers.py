from __future__ import annotations

import sqlite3

from backend.app.chat.infrastructure.persistence.models import (
    AssetRecord,
    ConversationRecord,
    MessagePartRecord,
    MessageRecord,
    UploadRecord,
)
from backend.app.chat.infrastructure.persistence.queries import build_message_parts_query


def conversation_from_row(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_message_preview=row["last_message_preview"],
        message_count=row["message_count"],
    )


def upload_from_row(row: sqlite3.Row) -> UploadRecord:
    return UploadRecord(
        id=row["id"],
        media_type=row["media_type"],
        storage_path=row["storage_path"],
        byte_size=row["byte_size"],
        created_at=row["created_at"],
    )


def asset_from_row(row: sqlite3.Row) -> AssetRecord:
    return AssetRecord(
        id=row["id"],
        message_id=row["message_id"],
        media_type=row["media_type"],
        storage_path=row["storage_path"],
        byte_size=row["byte_size"],
        created_at=row["created_at"],
    )


def build_message_records(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
) -> list[MessageRecord]:
    if not rows:
        return []

    message_ids = [row["id"] for row in rows]
    part_rows = connection.execute(
        build_message_parts_query(len(message_ids)),
        message_ids,
    ).fetchall()
    parts_by_message: dict[str, list[MessagePartRecord]] = {
        message_id: [] for message_id in message_ids
    }
    for part_row in part_rows:
        asset = None
        if part_row["asset_id"]:
            asset = AssetRecord(
                id=part_row["asset_id"],
                message_id=part_row["asset_message_id"],
                media_type=part_row["asset_media_type"],
                storage_path=part_row["asset_storage_path"],
                byte_size=part_row["asset_byte_size"],
                created_at=part_row["asset_created_at"],
            )
        parts_by_message[part_row["message_id"]].append(
            MessagePartRecord(
                type=part_row["part_type"],
                text=part_row["text_content"],
                asset=asset,
            )
        )

    return [
        MessageRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            status=row["status"],
            preview_text=row["preview_text"],
            text_content=row["text_content"],
            model=row["model"],
            finish_reason=row["finish_reason"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            parts=parts_by_message[row["id"]],
        )
        for row in rows
    ]
