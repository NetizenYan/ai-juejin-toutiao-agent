"""常驻 MCP 会话：每个 MCP server 一个长期运行的 stdio 子进程，供所有请求复用。

以前每条消息都新起一个子进程（检索 server 约 1.3s，web server 约 1.1s），进程里的
Qdrant/embedding 客户端、数据库连接池和 OCR 模型也每次重新加载。现在：

- 子进程由一个后台任务持有：stdio_client 的 anyio 作用域必须在同一个任务里进出，
  所以不能在请求里打开、在别的请求里关闭；
- ClientSession 按 JSON-RPC 请求号复用，多个请求可以并发调用；
- 调用出现传输层错误（子进程退出、管道断开）时标记为损坏，下一次取用时重启；
- 按事件循环缓存：测试里每个 asyncio.run 都是新循环，不会拿到别的循环里的会话。

MCP_RESIDENT_SESSIONS=false 时退回到每次请求新起子进程。
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from config.ai_conf import settings

logger = logging.getLogger(__name__)

# Errors that mean the transport is gone, not that one tool failed.
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    BrokenPipeError,
    ConnectionError,
    EOFError,
    McpError,
)


class ResidentSession:
    def __init__(self, name: str, params: Callable[[], StdioServerParameters]):
        self.name = name
        self._params = params
        self._session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._lock = asyncio.Lock()
        self.broken = False
        self.starts = 0

    def _alive(self) -> bool:
        return self._session is not None and self._task is not None and not self._task.done() and not self.broken

    async def get(self) -> ClientSession:
        async with self._lock:
            if self._alive():
                return self._session
            await self._close_locked()
            ready: asyncio.Future = asyncio.get_running_loop().create_future()
            self._stop = asyncio.Event()
            self.broken = False
            self._task = asyncio.create_task(self._own(ready, self._stop), name=f"mcp-resident-{self.name}")
            self._session = await ready
            self.starts += 1
            _SESSION_OWNERS[self._session] = self
            return self._session

    async def _own(self, ready: asyncio.Future, stop: asyncio.Event) -> None:
        try:
            async with stdio_client(self._params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.set_result(session)
                    await stop.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(repr(exc)))
            elif not isinstance(exc, asyncio.CancelledError):
                logger.warning("resident MCP session %s ended: %r", self.name, exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            # A replaced (cancelled) owner must not flag the session that replaced it.
            if self._task is asyncio.current_task():
                self.broken = True

    async def _close_locked(self) -> None:
        task, stop = self._task, self._stop
        self._session, self._task, self._stop = None, None, None
        if task is None:
            return
        if stop is not None:
            stop.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except BaseException:  # noqa: BLE001 - a stuck server is killed with its task
            task.cancel()

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()


_RESIDENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, ResidentSession]]" = weakref.WeakKeyDictionary()
_SESSION_OWNERS: "weakref.WeakKeyDictionary[ClientSession, ResidentSession]" = weakref.WeakKeyDictionary()


def resident(name: str, params: Callable[[], StdioServerParameters]) -> ResidentSession:
    by_name = _RESIDENTS.setdefault(asyncio.get_running_loop(), {})
    if name not in by_name:
        by_name[name] = ResidentSession(name, params)
    return by_name[name]


def mark_broken(session: ClientSession) -> None:
    """Called after a transport error so the next request restarts the server."""
    owner = _SESSION_OWNERS.get(session)
    if owner is not None:
        owner.broken = True


@asynccontextmanager
async def mcp_session(name: str, params: Callable[[], StdioServerParameters]) -> AsyncIterator[ClientSession]:
    if not settings.mcp_resident_sessions:
        async with stdio_client(params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return
    session = await resident(name, params).get()
    try:
        yield session
    except TRANSPORT_ERRORS:
        mark_broken(session)
        raise


async def close_all() -> None:
    """App shutdown: stop every resident server owned by the running loop."""
    for owner in list(_RESIDENTS.get(asyncio.get_running_loop(), {}).values()):
        await owner.close()
