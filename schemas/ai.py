from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: Optional[int] = Field(None, alias="sessionId", description="会话ID，不传则新建")

    model_config = {"populate_by_name": True}
