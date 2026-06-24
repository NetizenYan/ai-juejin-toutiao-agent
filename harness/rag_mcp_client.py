"""MCP client for the RAG MCP server（语义检索）。复用通用 list_tool_defs/call_tool。"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.rag_server"],
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
    )


@asynccontextmanager
async def rag_session():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
