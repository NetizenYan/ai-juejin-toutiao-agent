"""LLM 客户端封装：屏蔽供应商差异，对上层只暴露流式/非流式接口。

注意 gpt-oss 等 thinking 模型会把思考链放在 delta 的 reasoning 字段，
这里只输出 content（最终答案），reasoning 不推给用户。

主模型余额/额度耗尽（HTTP 402 等）时，自动切到 LLM_FALLBACK_* 配置的备用模型重试，
并在冷却期内直接走备用；其它错误照常抛出，不掩盖真实故障。
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from config.ai_conf import get_llm_client, get_llm_fallback_client, settings

logger = logging.getLogger(__name__)

REASONING_DELTA_FIELDS = ("reasoning_content", "reasoning", "thinking")
_QUOTA_MARKERS = ("insufficient balance", "insufficient_balance", "insufficient_quota", "quota exceeded", "余额不足")
_primary_exhausted_until = 0.0


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
    thinking_style: str = "deepseek",
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
        if thinking_style == "enable_thinking":
            extra_body["enable_thinking"] = True
        else:
            extra_body["thinking"] = {"type": "enabled"}
        request_kwargs["extra_body"] = extra_body
    return request_kwargs


def is_quota_error(exc: BaseException) -> bool:
    """Exhausted balance/quota: worth switching provider. Timeouts and bad requests are not."""
    if getattr(exc, "status_code", None) == 402:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_MARKERS)


@dataclass(frozen=True)
class _Target:
    client: Any
    model: str
    reasoning_effort: str
    thinking_enabled: bool
    thinking_style: str
    is_fallback: bool = False


class LLMClient:
    def __init__(self):
        self._client = get_llm_client()
        self.model = settings.llm_model
        self._fallback_client = get_llm_fallback_client()
        self.last_model = self.model

    def _targets(self) -> list[_Target]:
        primary = _Target(self._client, self.model, settings.llm_reasoning_effort,
                          settings.llm_thinking_enabled, settings.llm_thinking_style)
        if self._fallback_client is None:
            return [primary]
        fallback = _Target(self._fallback_client, settings.llm_fallback_model, settings.llm_fallback_reasoning_effort,
                           settings.llm_fallback_thinking_enabled, settings.llm_fallback_thinking_style, is_fallback=True)
        if time.monotonic() < _primary_exhausted_until:
            return [fallback]
        return [primary, fallback]

    async def _create(self, messages: list[dict], *, stream: bool, tools: Optional[list] = None, **kwargs):
        global _primary_exhausted_until
        targets = self._targets()
        for target in targets:
            request_kwargs = build_chat_completion_kwargs(
                model=target.model,
                messages=messages,
                stream=stream,
                reasoning_effort=target.reasoning_effort,
                thinking_enabled=target.thinking_enabled,
                thinking_style=target.thinking_style,
                tools=tools,
                **kwargs,
            )
            try:
                response = await target.client.chat.completions.create(**request_kwargs)
            except Exception as exc:  # noqa: BLE001 - only quota errors switch provider
                if target.is_fallback or target is targets[-1] or not is_quota_error(exc):
                    raise
                _primary_exhausted_until = time.monotonic() + settings.llm_fallback_cooldown_seconds
                logger.warning("primary LLM %s out of balance/quota (%s); using fallback %s",
                               target.model, exc, settings.llm_fallback_model)
                continue
            self.last_model = target.model
            return response
        raise RuntimeError("no LLM target available")

    async def stream_content(self, messages: list[dict], tools: Optional[list] = None) -> AsyncIterator[str]:
        """流式输出最终答案的 content 增量。"""
        stream = await self._create(messages, stream=True, tools=tools)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = extract_stream_content(delta)
            if content:
                yield content

    async def complete(self, messages: list[dict], **kwargs) -> str:
        """非流式，返回完整答案（备用 / 兜底）。"""
        resp = await self._create(messages, stream=False, **kwargs)
        return resp.choices[0].message.content or ""

    async def complete_message(self, messages: list[dict], **kwargs):
        """非流式，返回原始 message（用于读取受控 tool_calls）。"""
        resp = await self._create(messages, stream=False, **kwargs)
        return resp.choices[0].message
