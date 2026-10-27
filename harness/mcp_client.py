"""MCP 客户端：harness 通过 stdio 连接业务 MCP server，发现并调用业务工具。

设计：server 子进程常驻、跨请求复用（harness/mcp_pool.py）；business_session() 取得共享会话。
模型只拿到 list_tool_defs() 给出的 OpenAI 工具描述；真正执行由 Harness 经本客户端完成。
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters

from harness.mcp_pool import TRANSPORT_ERRORS, mark_broken, mcp_session

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_params() -> StdioServerParameters:
    # 用当前解释器以模块方式启动业务 server，cwd 设为项目根以便 `-m` 解析
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.business_server"],
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
    )


@asynccontextmanager
async def business_session():
    async with mcp_session("business", _server_params) as session:
        yield session


async def list_tool_defs(session: ClientSession) -> list[dict]:
    """返回 OpenAI tools 格式的工具描述，喂给支持 function calling 的模型。"""
    listed = await session.list_tools()
    defs: list[dict] = []
    for tool in listed.tools:
        defs.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        })
    return defs


def _extract_result(result) -> dict:
    """把 MCP CallToolResult 归一成 dict。"""
    structured = getattr(result, "structuredContent", None)
    if structured:
        # FastMCP 对返回 dict 的工具会包一层 {"result": ...} 或直接给字段；都尽量还原
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return {"text": text}
    return {}


async def call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    try:
        result = await session.call_tool(name, arguments)
    except TRANSPORT_ERRORS:
        mark_broken(session)  # the server is gone: the next request starts a fresh one
        raise
    if getattr(result, "isError", False):
        return {"tool": name, "error": "tool execution failed", "evidence_ids": []}
    return _extract_result(result)
