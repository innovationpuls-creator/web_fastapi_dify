CONVERSATION_SUMMARY_SELECT = """
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
"""

LIST_CONVERSATIONS_QUERY = f"""
    {CONVERSATION_SUMMARY_SELECT}
    ORDER BY c.updated_at DESC, c.created_at DESC
"""

GET_CONVERSATION_QUERY = f"""
    {CONVERSATION_SUMMARY_SELECT}
    WHERE c.id = ?
"""

LIST_MESSAGES_QUERY = """
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
"""

GET_MESSAGE_QUERY = """
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
"""

GET_UPLOAD_QUERY = """
    SELECT id, media_type, storage_path, byte_size, created_at
    FROM uploads
    WHERE id = ?
"""

GET_ASSET_QUERY = """
    SELECT id, message_id, media_type, storage_path, byte_size, created_at
    FROM assets
    WHERE id = ?
"""

GET_EXPIRED_UPLOADS_QUERY = """
    SELECT storage_path
    FROM uploads
    WHERE created_at < ?
"""

GET_CONVERSATION_EXISTS_QUERY = """
    SELECT 1
    FROM conversations
    WHERE id = ?
"""

GET_CONVERSATION_ASSET_PATHS_QUERY = """
    SELECT a.storage_path
    FROM assets AS a
    JOIN messages AS m ON m.id = a.message_id
    WHERE m.conversation_id = ?
"""

MESSAGE_PARTS_QUERY_TEMPLATE = """
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
"""


def build_message_parts_query(message_count: int) -> str:
    placeholders = ", ".join("?" for _ in range(message_count))
    return MESSAGE_PARTS_QUERY_TEMPLATE.format(placeholders=placeholders)
