"""MCP client for the guarded web MCP server."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from mcp import StdioServerParameters

from harness.mcp_pool import mcp_session

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=os.getenv("WEB_MCP_PYTHON", sys.executable),
        args=["-m", "mcp_servers.web_server"],
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
    )


@asynccontextmanager
async def web_session():
    async with mcp_session("web", _server_params) as session:
        yield session
