"""LLM 客户端封装：屏蔽供应商差异，对上层只暴露流式/非流式接口。

注意 gpt-oss 等 thinking 模型会把思考链放在 delta 的 reasoning 字段，
这里只输出 content（最终答案），reasoning 不推给用户。
"""
from typing import AsyncIterator, Optional

from config.ai_conf import get_llm_client, settings


REASONING_DELTA_FIELDS = ("reasoning_content", "reasoning", "thinking")


def extract_stream_content(delta) -> str:
    """Return only final-answer content; provider reasoning fields stay internal."""
    content = getattr(delta, "content", None)
    if content:
        return content
    return ""


def build_chat_completion_kwargs(
    *,
    model: str,
    messages: list[dict],
    stream: bool,
    reasoning_effort: str = "",
    thinking_enabled: bool = False,
    tools: Optional[list] = None,
    **kwargs,
) -> dict:
    request_kwargs = {"model": model, "messages": messages, "stream": stream, **kwargs}
    if tools:
        request_kwargs["tools"] = tools
    if reasoning_effort:
        request_kwargs["reasoning_effort"] = reasoning_effort
    if thinking_enabled:
        extra_body = dict(request_kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "enabled"}
        request_kwargs["extra_body"] = extra_body
    return request_kwargs


class LLMClient:
    def __init__(self):
        self._client = get_llm_client()
        self.model = settings.llm_model

    async def stream_content(self, messages: list[dict], tools: Optional[list] = None) -> AsyncIterator[str]:
        """流式输出最终答案的 content 增量。"""
        kwargs = build_chat_completion_kwargs(
            model=self.model,
            messages=messages,
            stream=True,
            reasoning_effort=settings.llm_reasoning_effort,
            thinking_enabled=settings.llm_thinking_enabled,
            tools=tools,
        )
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = extract_stream_content(delta)
            if content:
                yield content

    async def complete(self, messages: list[dict], **kwargs) -> str:
        """非流式，返回完整答案（备用 / 兜底）。"""
        request_kwargs = build_chat_completion_kwargs(
            model=self.model,
            messages=messages,
            stream=False,
            reasoning_effort=settings.llm_reasoning_effort,
            thinking_enabled=settings.llm_thinking_enabled,
            **kwargs,
        )
        resp = await self._client.chat.completions.create(**request_kwargs)
        return resp.choices[0].message.content or ""

    async def complete_message(self, messages: list[dict], **kwargs):
        """非流式，返回原始 message（用于读取受控 tool_calls）。"""
        request_kwargs = build_chat_completion_kwargs(
            model=self.model,
            messages=messages,
            stream=False,
            reasoning_effort=settings.llm_reasoning_effort,
            thinking_enabled=settings.llm_thinking_enabled,
            **kwargs,
        )
        resp = await self._client.chat.completions.create(**request_kwargs)
        return resp.choices[0].message
