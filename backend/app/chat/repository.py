from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4


MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["completed", "streaming", "failed", "cancelled"]
MessagePartType = Literal["text", "image"]


@dataclass(frozen=True)
class UploadRecord:
    id: str
    media_type: str
    storage_path: str
    byte_size: int
    created_at: str


@dataclass(frozen=True)
class AssetRecord:
    id: str
    message_id: str
    media_type: str
    storage_path: str
    byte_size: int
    created_at: str


@dataclass(frozen=True)
class MessagePartRecord:
    type: MessagePartType
    text: str | None = None
    asset: AssetRecord | None = None


@dataclass(frozen=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: MessageRole
    status: MessageStatus
    preview_text: str
    text_content: str
    model: str | None
    finish_reason: str | None
    error: str | None
    created_at: str
    updated_at: str
    parts: list[MessagePartRecord]


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    title: str
    created_at: str
    updated_at: str
    last_message_preview: str
    message_count: int


@dataclass(frozen=True)
class NewAsset:
    media_type: str
    storage_path: str
    byte_size: int
    id: str = ""

    def with_id(self) -> "NewAsset":
        return NewAsset(
            id=self.id or uuid4().hex,
            media_type=self.media_type,
            storage_path=self.storage_path,
            byte_size=self.byte_size,
        )


@dataclass(frozen=True)
class NewMessagePart:
    type: MessagePartType
    text: str | None = None
    asset: NewAsset | None = None


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
        self, conversation_id: str
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
            if not self._table_exists(connection, "conversations"):
                connection.executescript(self._schema_sql())
            else:
                self._migrate_messages_statuses(connection)
                connection.executescript(self._supporting_schema_sql())
            connection.commit()

    @staticmethod
    def _schema_sql() -> str:
        return """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
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

            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                media_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                part_index INTEGER NOT NULL,
                part_type TEXT NOT NULL CHECK(part_type IN ('text', 'image')),
                text_content TEXT,
                asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                UNIQUE(message_id, part_index)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created_at
                ON messages(conversation_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_parts_message_index
                ON message_parts(message_id, part_index);

            CREATE INDEX IF NOT EXISTS idx_uploads_created_at
                ON uploads(created_at);
        """

    @staticmethod
    def _supporting_schema_sql() -> str:
        return """
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                media_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                part_index INTEGER NOT NULL,
                part_type TEXT NOT NULL CHECK(part_type IN ('text', 'image')),
                text_content TEXT,
                asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                UNIQUE(message_id, part_index)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created_at
                ON messages(conversation_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_parts_message_index
                ON message_parts(message_id, part_index);

            CREATE INDEX IF NOT EXISTS idx_uploads_created_at
                ON uploads(created_at);
        """

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
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

    def _create_conversation(
        self, title: str, conversation_id: str, created_at: str
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
            rows = connection.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COALESCE(
                        (
                            SELECT m.preview_text
                            FROM messages AS m
                            WHERE m.conversation_id = c.id
                            ORDER BY
                                m.updated_at DESC,
                                m.created_at DESC,
                                CASE m.role WHEN 'assistant' THEN 0 ELSE 1 END ASC,
                                m.id DESC
                            LIMIT 1
                        ),
                        ''
                    ) AS last_message_preview,
                    (
                        SELECT COUNT(*)
                        FROM messages AS m
                        WHERE m.conversation_id = c.id
                    ) AS message_count
                FROM conversations AS c
                ORDER BY c.updated_at DESC, c.created_at DESC
                """
            ).fetchall()
            return [self._conversation_from_row(row) for row in rows]

    def _get_conversation_detail(
        self, conversation_id: str
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
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    updated_at = ?
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
            rows = connection.execute(
                """
                SELECT storage_path
                FROM uploads
                WHERE created_at < ?
                """,
                (created_before,),
            ).fetchall()
            connection.execute(
                "DELETE FROM uploads WHERE created_at < ?",
                (created_before,),
            )
            connection.commit()
            return [Path(row["storage_path"]) for row in rows]

    def _get_asset(self, asset_id: str) -> AssetRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, message_id, media_type, storage_path, byte_size, created_at
                FROM assets
                WHERE id = ?
                """,
                (asset_id,),
            ).fetchone()
            return self._asset_from_row(row) if row else None

    def _delete_conversation(self, conversation_id: str) -> list[Path] | None:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if exists is None:
                return None

            asset_rows = connection.execute(
                """
                SELECT a.storage_path
                FROM assets AS a
                JOIN messages AS m ON m.id = a.message_id
                WHERE m.conversation_id = ?
                """,
                (conversation_id,),
            ).fetchall()
            connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            connection.commit()
            return [Path(row["storage_path"]) for row in asset_rows]

    def _get_conversation_with_connection(
        self, connection: sqlite3.Connection, conversation_id: str
    ) -> ConversationRecord | None:
        row = connection.execute(
            """
            SELECT
                c.id,
                c.title,
                c.created_at,
                c.updated_at,
                COALESCE(
                    (
                        SELECT m.preview_text
                        FROM messages AS m
                        WHERE m.conversation_id = c.id
                        ORDER BY
                            m.updated_at DESC,
                            m.created_at DESC,
                            CASE m.role WHEN 'assistant' THEN 0 ELSE 1 END ASC,
                            m.id DESC
                        LIMIT 1
                    ),
                    ''
                ) AS last_message_preview,
                (
                    SELECT COUNT(*)
                    FROM messages AS m
                    WHERE m.conversation_id = c.id
                ) AS message_count
            FROM conversations AS c
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()
        return self._conversation_from_row(row) if row else None

    def _list_messages_with_connection(
        self, connection: sqlite3.Connection, conversation_id: str
    ) -> list[MessageRecord]:
        rows = connection.execute(
            """
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
            FROM messages
            WHERE conversation_id = ?
            ORDER BY
                created_at ASC,
                updated_at ASC,
                CASE role WHEN 'user' THEN 0 ELSE 1 END ASC,
                id ASC
            """,
            (conversation_id,),
        ).fetchall()
        return self._build_message_records(connection, rows)

    def _get_message_with_connection(
        self, connection: sqlite3.Connection, message_id: str
    ) -> MessageRecord | None:
        row = connection.execute(
            """
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
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            return None
        return self._build_message_records(connection, [row])[0]

    def _get_upload_with_connection(
        self, connection: sqlite3.Connection, upload_id: str
    ) -> UploadRecord | None:
        row = connection.execute(
            """
            SELECT id, media_type, storage_path, byte_size, created_at
            FROM uploads
            WHERE id = ?
            """,
            (upload_id,),
        ).fetchone()
        return self._upload_from_row(row) if row else None

    def _build_message_records(
        self, connection: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> list[MessageRecord]:
        if not rows:
            return []

        message_ids = [row["id"] for row in rows]
        placeholders = ", ".join("?" for _ in message_ids)
        part_rows = connection.execute(
            f"""
            SELECT
                mp.message_id,
                mp.part_type,
                mp.text_content,
                a.id AS asset_id,
                a.message_id AS asset_message_id,
                a.media_type AS asset_media_type,
                a.storage_path AS asset_storage_path,
                a.byte_size AS asset_byte_size,
                a.created_at AS asset_created_at
            FROM message_parts AS mp
            LEFT JOIN assets AS a ON a.id = mp.asset_id
            WHERE mp.message_id IN ({placeholders})
            ORDER BY mp.message_id ASC, mp.part_index ASC
            """,
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

    def _insert_message_parts(
        self,
        connection: sqlite3.Connection,
        message_id: str,
        parts: list[NewMessagePart],
        created_at: str,
    ) -> None:
        for index, part in enumerate(parts):
            asset_id = None
            if part.asset:
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

    @staticmethod
    def _conversation_from_row(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_message_preview=row["last_message_preview"],
            message_count=row["message_count"],
        )

    @staticmethod
    def _upload_from_row(row: sqlite3.Row) -> UploadRecord:
        return UploadRecord(
            id=row["id"],
            media_type=row["media_type"],
            storage_path=row["storage_path"],
            byte_size=row["byte_size"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(
            id=row["id"],
            message_id=row["message_id"],
            media_type=row["media_type"],
            storage_path=row["storage_path"],
            byte_size=row["byte_size"],
            created_at=row["created_at"],
        )
