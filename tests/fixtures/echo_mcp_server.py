"""Minimal stdio MCP server for tests/test_mcp_pool.py."""
import asyncio
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool()
async def whoami() -> dict:
    return {"pid": os.getpid()}


@mcp.tool()
async def sleep(seconds: float) -> dict:
    await asyncio.sleep(seconds)
    return {"pid": os.getpid(), "slept": seconds}


@mcp.tool()
async def die() -> dict:
    os._exit(1)


if __name__ == "__main__":
    mcp.run()
