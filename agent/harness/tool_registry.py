"""Allowed Agent tools and deterministic argument validation."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolPolicyError(ValueError):
    """Raised when a model-requested tool call violates harness policy."""


class NewsSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=8)


class NewsDetailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: int = Field(..., ge=1)


class UserRecentHistoryModelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=8)


class RecommendNewsModelArgs(BaseModel):
    # user_id 由 Harness 注入；模型只能给 limit
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=8)


class RetrieveNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=50)  # 放宽以支持召回-精排


class WebFetchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=8, max_length=2048)


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=240)
    limit: int = Field(default=5, ge=1, le=10)


class WebCaptureOcrArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=8, max_length=2048)
    source_name: str = Field(default="", max_length=80)
    min_ocr_confidence: float = Field(default=0.35, ge=0.0, le=1.0)


TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "news_search": NewsSearchArgs,
    "news_detail": NewsDetailArgs,
    "user_recent_history": UserRecentHistoryModelArgs,
    "recommend_news": RecommendNewsModelArgs,
    "retrieve_news": RetrieveNewsArgs,
    "web_fetch": WebFetchArgs,
    "web_search": WebSearchArgs,
    "web_capture_ocr": WebCaptureOcrArgs,
}

# 需要后端注入认证 user_id 的用户级工具（模型不得自行指定 user_id）
_USER_SCOPED_TOOLS = {"user_recent_history", "recommend_news"}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "Search approved in-site news articles by keyword. Use for site news Q&A and recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword or user question to search in news title/content."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_detail",
            "description": "Read one approved in-site news article by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "news_id": {"type": "integer", "minimum": 1, "description": "News article id."},
                },
                "required": ["news_id"],
                "additionalProperties": False,
            },
        },
    },
]


def _decode_arguments(arguments: Any) -> dict:
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ToolPolicyError(f"工具参数不是合法 JSON: {exc}") from exc
    elif isinstance(arguments, dict):
        decoded = arguments
    else:
        raise ToolPolicyError("工具参数必须是 JSON 对象")

    if not isinstance(decoded, dict):
        raise ToolPolicyError("工具参数必须是 JSON 对象")
    return decoded


def validate_tool_arguments(tool_name: str, arguments: Any, auth_user_id: int | None = None) -> dict:
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        raise ToolPolicyError(f"不允许调用工具: {tool_name}")

    try:
        parsed = schema.model_validate(_decode_arguments(arguments))
    except ValidationError as exc:
        raise ToolPolicyError(f"工具参数校验失败: {exc}") from exc

    result = parsed.model_dump()
    if tool_name in {"web_fetch", "web_capture_ocr"}:
        scheme = urlsplit(result["url"]).scheme
        if scheme not in {"http", "https"}:
            raise ToolPolicyError(f"{tool_name} 只允许 http(s) URL")
    if tool_name in _USER_SCOPED_TOOLS:
        if auth_user_id is None:
            raise ToolPolicyError(f"{tool_name} 必须由后端注入认证用户 ID")
        result["user_id"] = auth_user_id
    return result
