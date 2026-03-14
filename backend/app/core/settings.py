from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OPENAI_SYSTEM_PROMPT = (
    "You are a multilingual AI assistant that reasons carefully and answers with the level of "
    "depth the task needs. "
    "Answer the user's latest request directly in the same language as that request unless the "
    "user explicitly asks for another language. "
    "Do not echo prior conversation turns, role labels, transcript snippets, or the user's "
    "message unless quoting it is genuinely necessary. "
    "If you emit a reasoning trace, wrap it exactly once inside <think>...</think> and place "
    "the final user-facing answer after </think>. Do not nest or repeat <think> blocks. "
    "Keep the final answer clear, concrete, and well structured. "
    "When the response explains steps, concepts, or multiple takeaways, prefer helpful Markdown "
    "headings and lists so the answer is easy to scan. "
    "When explaining code, scripts, or commands, explain by block or line when helpful, and "
    "call out what each part does plus any important caveats or assumptions."
)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "dify-fastapi"
    app_version: str = "1.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    openai_api_key: str = Field(min_length=1)
    openai_base_url: str = Field(min_length=1)
    openai_model: str = Field(min_length=1)
    openai_system_prompt: str = Field(default=DEFAULT_OPENAI_SYSTEM_PROMPT, min_length=1)

    openai_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    openai_read_timeout_seconds: float = Field(default=60.0, gt=0)
    openai_write_timeout_seconds: float = Field(default=10.0, gt=0)
    health_deep_timeout_seconds: float = Field(default=5.0, gt=0)
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ]
    )
    chat_database_path: Path = Path("data/chat.sqlite3")
    chat_assets_dir: Path = Path("data/chat-assets")
    chat_uploads_dir: Path = Path("data/chat-uploads")
    chat_max_images_per_message: int = Field(default=4, ge=1, le=8)
    chat_max_image_bytes: int = Field(default=5_000_000, ge=1_000_000)
    chat_upload_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_allow_origins(cls, value: object) -> object:
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            return items or [
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:4173",
                "http://localhost:4173",
            ]
        return value


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
