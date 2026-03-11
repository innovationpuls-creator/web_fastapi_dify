from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.app.chat.infrastructure.persistence.models import (
    AssetRecord,
    ConversationRecord,
    MessageRecord,
    MessageRole,
    MessageStatus,
    NewMessagePart,
    UploadRecord,
)
from backend.app.chat.infrastructure.persistence.queries import (
    GET_ASSET_QUERY,
    GET_CONVERSATION_ASSET_PATHS_QUERY,
    GET_CONVERSATION_EXISTS_QUERY,
    GET_CONVERSATION_QUERY,
    GET_EXPIRED_UPLOADS_QUERY,
    GET_MESSAGE_QUERY,
    GET_UPLOAD_QUERY,
    LIST_CONVERSATIONS_QUERY,
    LIST_MESSAGES_QUERY,
)
from backend.app.chat.infrastructure.persistence.row_mappers import (
    asset_from_row,
    build_message_records,
    conversation_from_row,
    upload_from_row,
)
from backend.app.chat.infrastructure.persistence.schema import SCHEMA_SQL


class ChatRepository:
    def __init__(
        self,
        database_path: Path,
        assets_dir: Path,
        uploads_dir: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.assets_dir = assets_dir
        self.uploads_dir = uploads_dir or assets_dir.parent / "chat-uploads"

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    async def create_conversation(
        self,
        *,
        title: str,
        conversation_id: str | None = None,
        created_at: str,
    ) -> ConversationRecord:
        return await asyncio.to_thread(
            self._create_conversation,
            title,
            conversation_id or uuid4().hex,
            created_at,
        )

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        return await asyncio.to_thread(self._get_conversation, conversation_id)

    async def list_conversations(self) -> list[ConversationRecord]:
        return await asyncio.to_thread(self._list_conversations)

    async def get_conversation_detail(
        self,
        conversation_id: str,
    ) -> tuple[ConversationRecord, list[MessageRecord]] | None:
        return await asyncio.to_thread(self._get_conversation_detail, conversation_id)

    async def list_messages(self, conversation_id: str) -> list[MessageRecord]:
        return await asyncio.to_thread(self._list_messages, conversation_id)

    async def get_message(self, message_id: str) -> MessageRecord | None:
        return await asyncio.to_thread(self._get_message, message_id)

    async def create_message(
        self,
        *,
        conversation_id: str,
        role: MessageRole,
        status: MessageStatus,
        preview_text: str,
        text_content: str,
        parts: list[NewMessagePart],
        created_at: str,
        message_id: str | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        error: str | None = None,
        thinking_completed_at: str | None = None,
    ) -> MessageRecord:
        return await asyncio.to_thread(
            self._create_message,
            conversation_id,
            role,
            status,
            preview_text,
            text_content,
            parts,
            created_at,
            message_id or uuid4().hex,
            model,
            finish_reason,
            error,
            thinking_completed_at,
        )

    async def update_message(
        self,
        *,
        message_id: str,
        status: MessageStatus,
        preview_text: str,
        text_content: str,
        updated_at: str,
        model: str | None = None,
        finish_reason: str | None = None,
        error: str | None = None,
        thinking_completed_at: str | None = None,
    ) -> MessageRecord | None:
        return await asyncio.to_thread(
            self._update_message,
            message_id,
            status,
            preview_text,
            text_content,
            updated_at,
            model,
            finish_reason,
            error,
            thinking_completed_at,
        )

    async def create_upload(
        self,
        *,
        media_type: str,
        storage_path: str,
        byte_size: int,
        created_at: str,
        upload_id: str | None = None,
    ) -> UploadRecord:
        return await asyncio.to_thread(
            self._create_upload,
            upload_id or uuid4().hex,
            media_type,
            storage_path,
            byte_size,
            created_at,
        )

    async def get_upload(self, upload_id: str) -> UploadRecord | None:
        return await asyncio.to_thread(self._get_upload, upload_id)

    async def pop_upload(self, upload_id: str) -> UploadRecord | None:
        return await asyncio.to_thread(self._pop_upload, upload_id)

    async def delete_upload(self, upload_id: str) -> Path | None:
        return await asyncio.to_thread(self._delete_upload, upload_id)

    async def delete_expired_uploads(self, created_before: str) -> list[Path]:
        return await asyncio.to_thread(self._delete_expired_uploads, created_before)

    async def get_asset(self, asset_id: str) -> AssetRecord | None:
        return await asyncio.to_thread(self._get_asset, asset_id)

    async def delete_conversation(self, conversation_id: str) -> list[Path] | None:
        return await asyncio.to_thread(self._delete_conversation, conversation_id)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            self._migrate_messages_statuses(connection)
            connection.executescript(SCHEMA_SQL)
            self._ensure_message_columns(connection)
            connection.commit()

    def _create_conversation(
        self,
        title: str,
        conversation_id: str,
        created_at: str,
    ) -> ConversationRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, title, created_at, created_at),
            )
            connection.commit()
            return self._get_conversation_with_connection(connection, conversation_id)

    def _get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._connect() as connection:
            return self._get_conversation_with_connection(connection, conversation_id)

    def _list_conversations(self) -> list[ConversationRecord]:
        with self._connect() as connection:
            rows = connection.execute(LIST_CONVERSATIONS_QUERY).fetchall()
            return [conversation_from_row(row) for row in rows]

    def _get_conversation_detail(
        self,
        conversation_id: str,
    ) -> tuple[ConversationRecord, list[MessageRecord]] | None:
        with self._connect() as connection:
            conversation = self._get_conversation_with_connection(connection, conversation_id)
            if conversation is None:
                return None
            messages = self._list_messages_with_connection(connection, conversation_id)
            return conversation, messages

    def _list_messages(self, conversation_id: str) -> list[MessageRecord]:
        with self._connect() as connection:
            return self._list_messages_with_connection(connection, conversation_id)

    def _get_message(self, message_id: str) -> MessageRecord | None:
        with self._connect() as connection:
            return self._get_message_with_connection(connection, message_id)

    def _create_message(
        self,
        conversation_id: str,
        role: MessageRole,
        status: MessageStatus,
        preview_text: str,
        text_content: str,
        parts: list[NewMessagePart],
        created_at: str,
        message_id: str,
        model: str | None,
        finish_reason: str | None,
        error: str | None,
        thinking_completed_at: str | None = None,
    ) -> MessageRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id,
                    conversation_id,
                    role,
                    status,
                    preview_text,
                    text_content,
                    model,
                    finish_reason,
                    error,
                    created_at,
                    updated_at,
                    thinking_completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    status,
                    preview_text,
                    text_content,
                    model,
                    finish_reason,
                    error,
                    created_at,
                    created_at,
                    thinking_completed_at,
                ),
            )
            self._insert_message_parts(connection, message_id, parts, created_at)
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (created_at, conversation_id),
            )
            connection.commit()
            return self._get_message_with_connection(connection, message_id)

    def _update_message(
        self,
        message_id: str,
        status: MessageStatus,
        preview_text: str,
        text_content: str,
        updated_at: str,
        model: str | None,
        finish_reason: str | None,
        error: str | None,
        thinking_completed_at: str | None = None,
    ) -> MessageRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT conversation_id FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None

            connection.execute(
                """
                UPDATE messages
                SET status = ?,
                    preview_text = ?,
                    text_content = ?,
                    model = COALESCE(?, model),
                    finish_reason = ?,
                    error = ?,
                    updated_at = ?,
                    thinking_completed_at = COALESCE(?, thinking_completed_at)
                WHERE id = ?
                """,
                (
                    status,
                    preview_text,
                    text_content,
                    model,
                    finish_reason,
                    error,
                    updated_at,
                    thinking_completed_at,
                    message_id,
                ),
            )
            connection.execute("DELETE FROM message_parts WHERE message_id = ?", (message_id,))
            if text_content:
                self._insert_message_parts(
                    connection,
                    message_id,
                    [NewMessagePart(type="text", text=text_content)],
                    updated_at,
                )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (updated_at, row["conversation_id"]),
            )
            connection.commit()
            return self._get_message_with_connection(connection, message_id)

    def _ensure_message_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "thinking_completed_at" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN thinking_completed_at TEXT"
            )

    def _table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    def _migrate_messages_statuses(self, connection: sqlite3.Connection) -> None:
        if not self._table_exists(connection, "messages"):
            return

        row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'messages'
            """
        ).fetchone()
        schema_sql = (row["sql"] or "").lower() if row is not None else ""
        if "cancelled" in schema_sql:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                CREATE TABLE messages__new (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    status TEXT NOT NULL CHECK(
                        status IN ('completed', 'streaming', 'failed', 'cancelled')
                    ),
                    preview_text TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    model TEXT,
                    finish_reason TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                INSERT INTO messages__new (
                    id,
                    conversation_id,
                    role,
                    status,
                    preview_text,
                    text_content,
                    model,
                    finish_reason,
                    error,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    conversation_id,
                    role,
                    status,
                    preview_text,
                    text_content,
                    model,
                    finish_reason,
                    error,
                    created_at,
                    updated_at
                FROM messages;

                DROP TABLE messages;
                ALTER TABLE messages__new RENAME TO messages;
                """
            )
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def _create_upload(
        self,
        upload_id: str,
        media_type: str,
        storage_path: str,
        byte_size: int,
        created_at: str,
    ) -> UploadRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO uploads (id, media_type, storage_path, byte_size, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (upload_id, media_type, storage_path, byte_size, created_at),
            )
            connection.commit()
            return self._get_upload_with_connection(connection, upload_id)

    def _get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._connect() as connection:
            return self._get_upload_with_connection(connection, upload_id)

    def _pop_upload(self, upload_id: str) -> UploadRecord | None:
        with self._connect() as connection:
            record = self._get_upload_with_connection(connection, upload_id)
            if record is None:
                return None
            connection.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
            connection.commit()
            return record

    def _delete_upload(self, upload_id: str) -> Path | None:
        with self._connect() as connection:
            record = self._get_upload_with_connection(connection, upload_id)
            if record is None:
                return None
            connection.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
            connection.commit()
            return Path(record.storage_path)

    def _delete_expired_uploads(self, created_before: str) -> list[Path]:
        with self._connect() as connection:
            rows = connection.execute(GET_EXPIRED_UPLOADS_QUERY, (created_before,)).fetchall()
            connection.execute(
                "DELETE FROM uploads WHERE created_at < ?",
                (created_before,),
            )
            connection.commit()
            return [Path(row["storage_path"]) for row in rows]

    def _get_asset(self, asset_id: str) -> AssetRecord | None:
        with self._connect() as connection:
            row = connection.execute(GET_ASSET_QUERY, (asset_id,)).fetchone()
            return asset_from_row(row) if row else None

    def _delete_conversation(self, conversation_id: str) -> list[Path] | None:
        with self._connect() as connection:
            exists = connection.execute(
                GET_CONVERSATION_EXISTS_QUERY,
                (conversation_id,),
            ).fetchone()
            if exists is None:
                return None

            asset_rows = connection.execute(
                GET_CONVERSATION_ASSET_PATHS_QUERY,
                (conversation_id,),
            ).fetchall()
            connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            connection.commit()
            return [Path(row["storage_path"]) for row in asset_rows]

    def _get_conversation_with_connection(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
    ) -> ConversationRecord | None:
        row = connection.execute(GET_CONVERSATION_QUERY, (conversation_id,)).fetchone()
        return conversation_from_row(row) if row else None

    def _list_messages_with_connection(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
    ) -> list[MessageRecord]:
        rows = connection.execute(LIST_MESSAGES_QUERY, (conversation_id,)).fetchall()
        return build_message_records(connection, rows)

    def _get_message_with_connection(
        self,
        connection: sqlite3.Connection,
        message_id: str,
    ) -> MessageRecord | None:
        row = connection.execute(GET_MESSAGE_QUERY, (message_id,)).fetchone()
        if row is None:
            return None
        return build_message_records(connection, [row])[0]

    def _get_upload_with_connection(
        self,
        connection: sqlite3.Connection,
        upload_id: str,
    ) -> UploadRecord | None:
        row = connection.execute(GET_UPLOAD_QUERY, (upload_id,)).fetchone()
        return upload_from_row(row) if row else None

    def _insert_message_parts(
        self,
        connection: sqlite3.Connection,
        message_id: str,
        parts: list[NewMessagePart],
        created_at: str,
    ) -> None:
        for index, part in enumerate(parts):
            asset_id = None
            if part.asset is not None:
                asset = part.asset.with_id()
                connection.execute(
                    """
                    INSERT INTO assets (id, message_id, media_type, storage_path, byte_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset.id,
                        message_id,
                        asset.media_type,
                        asset.storage_path,
                        asset.byte_size,
                        created_at,
                    ),
                )
                asset_id = asset.id

            connection.execute(
                """
                INSERT INTO message_parts (message_id, part_index, part_type, text_content, asset_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    index,
                    part.type,
                    part.text,
                    asset_id,
                ),
            )
