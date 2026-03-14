SCHEMA_SQL = """
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
        input_tokens INTEGER,
        output_tokens INTEGER,
        total_tokens INTEGER,
        latency_ms REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        thinking_completed_at TEXT
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
