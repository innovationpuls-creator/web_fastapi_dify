"""Chat schemas for the conversation-driven multimodal API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TextInputPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=16_000)


class ImageInputPart(BaseModel):
    type: Literal["image"]
    media_type: Literal["image/png", "image/jpeg", "image/webp"] | None = None
    data_base64: str | None = Field(default=None, min_length=16)
    upload_id: str | None = Field(default=None, min_length=8, max_length=64)

    @model_validator(mode="after")
    def validate_source(self) -> "ImageInputPart":
        has_base64 = bool(self.data_base64)
        has_upload_id = bool(self.upload_id)
        if has_base64 == has_upload_id:
            raise ValueError("Image part requires exactly one of data_base64 or upload_id.")
        if has_base64 and self.media_type is None:
            raise ValueError("Image media_type is required when using data_base64.")
        return self


InputPart = Annotated[TextInputPart | ImageInputPart, Field(discriminator="type")]


class ChatInput(BaseModel):
    parts: list[InputPart] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_parts(self) -> "ChatInput":
        has_text = any(
            isinstance(part, TextInputPart) and part.text.strip() for part in self.parts
        )
        has_image = any(isinstance(part, ImageInputPart) for part in self.parts)
        if not has_text and not has_image:
            raise ValueError("At least one text or image part is required.")
        return self


class GenerationOptions(BaseModel):
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=2048, gt=0, le=8192)


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": None,
                "provider": "openai",
                "input": {
                    "parts": [
                        {"type": "text", "text": "Please analyze this image."},
                        {
                            "type": "image",
                            "upload_id": "upload_12345678",
                        },
                    ]
                },
                "generation": {
                    "temperature": 0.7,
                    "max_output_tokens": 2048,
                },
            }
        }
    )

    conversation_id: str | None = Field(default=None, min_length=8, max_length=64)
    provider: Literal["openai", "dify"] = "openai"
    input: ChatInput
    generation: GenerationOptions = Field(default_factory=GenerationOptions)


class MessageRegenerateRequest(BaseModel):
    generation: GenerationOptions = Field(default_factory=GenerationOptions)


class TextMessagePart(BaseModel):
    type: Literal["text"]
    text: str


class ImageMessagePart(BaseModel):
    type: Literal["image"]
    asset_id: str
    media_type: str
    url: str


class ChatUploadResponse(BaseModel):
    upload_id: str
    url: str
    media_type: str
    byte_size: int
    created_at: str


MessagePart = Annotated[
    TextMessagePart | ImageMessagePart,
    Field(discriminator="type"),
]


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    created_at: str
    last_message_preview: str
    message_count: int


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Conversation title cannot be empty.")
        if len(normalized) > 80:
            raise ValueError("Conversation title must be 80 characters or fewer.")
        return normalized


class MessageMetrics(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)


class ChatMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    status: Literal["completed", "streaming", "failed", "cancelled"]
    parts: list[MessagePart]
    created_at: str
    updated_at: str
    thinking_completed_at: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    error: str | None = None
    metrics: MessageMetrics | None = None


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessageResponse]


class CancelMessageResponse(BaseModel):
    message: ChatMessageResponse
    conversation: ConversationSummary


class ChatStreamEvent(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event": "meta",
                    "model": "qwen/qwen3.5-9b",
                    "conversation_id": "conv_123",
                    "user_message_id": "msg_user_123",
                    "assistant_message_id": "msg_assistant_123",
                    "title": "Analyze this image",
                },
                {
                    "event": "delta",
                    "model": "qwen/qwen3.5-9b",
                    "delta": "Here is what I notice...",
                },
                {
                    "event": "done",
                    "model": "qwen/qwen3.5-9b",
                    "finish_reason": "stop",
                },
            ]
        }
    )

    event: Literal["meta", "delta", "done", "error"]
    model: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    title: str | None = None
    delta: str = ""
    message: ChatMessageResponse | None = None
    conversation: ConversationSummary | None = None
    finish_reason: str | None = None
    error: str | None = None
