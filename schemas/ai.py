from typing import Optional

from pydantic import BaseModel, Field, field_validator

from config.ai_conf import settings


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: Optional[int] = Field(None, alias="sessionId", gt=0, description="会话ID，不传则新建")

    model_config = {"populate_by_name": True}

    @field_validator("message")
    @classmethod
    def _bounded_message(cls, value: str) -> str:
        # Every accepted message costs an LLM call: reject blank and oversized ones up front.
        text = value.strip()
        if not text:
            raise ValueError("消息不能为空")
        if len(text) > settings.ai_chat_max_message_chars:
            raise ValueError(f"消息过长，最多 {settings.ai_chat_max_message_chars} 字")
        return text
