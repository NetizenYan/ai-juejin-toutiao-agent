"""Web search across several backends with failover, cooldowns and a short result cache.

The free keyless backends (Baidu through a local open-websearch daemon, 360 through a self-hosted
SearXNG) start answering scrapers with CAPTCHA pages after a handful of queries, and sometimes only
return zero results without saying why. The router therefore:

- tries the configured backends in order and stops at the first one that returns usable results;
- classifies every attempt as ok / empty / blocked / error (plus cooling / throttled when skipped);
- puts a backend on cooldown after an explicit block (doubling per consecutive block, capped) and
  after repeated errors (daemon down); repeated empty answers count as a block, because both Baidu
  and 360 were seen to go silent (zero results, no error) once they had flagged the scraper;
- skips a backend called again within its minimum interval instead of hammering it, and only waits
  for it when every other backend has failed;
- caches successful results per query for a while, so a retried turn does not search again.

Breaker state is kept in a small JSON file so it survives the MCP subprocess being restarted.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlsplit

BackendFn = Callable[[object, str, int], Awaitable[list[dict]]]

ERRORS_BEFORE_COOLDOWN = 3
ERROR_COOLDOWN_SECONDS = 60
EMPTIES_BEFORE_COOLDOWN = 3
CACHE_MAX_ENTRIES = 256

_BLOCK_RE = re.compile(
    r"captcha|verification|anti-?bot|suspended|too many requests|rate.?limit|access denied|forbidden|"
    r"\b(?:403|429)\b|验证",
    re.IGNORECASE,
)


class SearchBlocked(Exception):
    """The backend answered with a CAPTCHA, a rate limit or an exhausted quota."""


def looks_blocked(message: str) -> bool:
    return bool(_BLOCK_RE.search(message or ""))


@dataclass
class BackendState:
    blocked_until: float = 0.0
    block_streak: int = 0
    error_streak: int = 0
    empty_streak: int = 0
    last_call: float = 0.0


@dataclass
class Attempt:
    backend: str
    outcome: str
    count: int = 0
    detail: str = ""


@dataclass
class SearchOutcome:
    items: list[dict]
    backend: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    cached: bool = False

    @property
    def failed(self) -> bool:
        """No backend answered at all: every one was blocked, broken, cooling or throttled."""
        return not self.items and not any(a.outcome in {"empty", "ok"} for a in self.attempts)

    @property
    def incomplete(self) -> bool:
        """Some backend answered, but at least one other could not be searched."""
        return not self.failed and any(a.outcome not in {"empty", "ok"} for a in self.attempts)


class WebSearchRouter:
    def __init__(
        self,
        backends: dict[str, BackendFn],
        order: list[str],
        *,
        state_path: str = "",
        block_cooldown: float = 600,
        block_cooldown_max: float = 21600,
        min_interval: float = 2.0,
        cache_ttl: float = 1800,
        keep_item: Callable[[dict], bool] = lambda item: True,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.order = [name for name in order if name in backends]
        self.backends = backends
        self.state_path = state_path
        self.block_cooldown = block_cooldown
        self.block_cooldown_max = block_cooldown_max
        self.min_interval = min_interval
        self.cache_ttl = cache_ttl
        self.keep_item = keep_item
        self.clock = clock
        self.sleep = sleep
        self._cache: dict[tuple[str, int], tuple[float, str, list[dict]]] = {}

    # ---- state -------------------------------------------------------------------------------
    def _load(self) -> dict[str, BackendState]:
        states = {name: BackendState() for name in self.order}
        if not self.state_path:
            return getattr(self, "_memory_state", states)
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return states
        for name in self.order:
            if isinstance(raw.get(name), dict):
                known = {key: raw[name][key] for key in asdict(BackendState()) if key in raw[name]}
                states[name] = BackendState(**known)
        return states

    def _save(self, states: dict[str, BackendState]) -> None:
        if not self.state_path:
            self._memory_state = states
            return
        try:
            directory = os.path.dirname(self.state_path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({name: asdict(state) for name, state in states.items()}, fh)
            os.replace(tmp, self.state_path)
        except OSError:
            pass  # the breaker degrades to per-call memory; searching still works

    def _record(self, state: BackendState, outcome: str, now: float) -> None:
        if outcome == "ok":
            state.block_streak = state.error_streak = state.empty_streak = 0
        elif outcome == "blocked":
            self._cool_down(state, now)
        elif outcome == "error":
            state.error_streak += 1
            if state.error_streak >= ERRORS_BEFORE_COOLDOWN:
                state.blocked_until = now + ERROR_COOLDOWN_SECONDS
                state.error_streak = 0
        elif outcome == "empty":
            state.empty_streak += 1
            if state.empty_streak >= EMPTIES_BEFORE_COOLDOWN:
                self._cool_down(state, now)
                state.empty_streak = 0

    def _cool_down(self, state: BackendState, now: float) -> None:
        state.block_streak += 1
        cooldown = min(self.block_cooldown * 2 ** (state.block_streak - 1), self.block_cooldown_max)
        state.blocked_until = now + cooldown

    # ---- search ------------------------------------------------------------------------------
    def _filter(self, raw: list[dict], limit: int) -> list[dict]:
        items, seen = [], set()
        for item in raw:
            url = item.get("url") or ""
            if not urlsplit(url).hostname or url in seen or not self.keep_item(item):
                continue
            seen.add(url)
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def _try(self, name: str, client, query: str, limit: int, state: BackendState) -> Attempt:
        state.last_call = self.clock()
        try:
            raw = await self.backends[name](client, query, limit)
        except SearchBlocked as exc:
            attempt = Attempt(name, "blocked", detail=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - any backend failure moves on to the next one
            outcome = "blocked" if looks_blocked(str(exc)) else "error"
            attempt = Attempt(name, outcome, detail=f"{type(exc).__name__}: {exc}"[:200])
        else:
            items = self._filter(raw or [], limit)
            attempt = Attempt(name, "ok" if items else "empty", count=len(items))
            attempt.items = items  # type: ignore[attr-defined]
        self._record(state, attempt.outcome, self.clock())
        return attempt

    async def search(self, client, query: str, limit: int) -> SearchOutcome:
        key = (" ".join((query or "").split()), limit)
        now = self.clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return SearchOutcome(items=list(hit[2]), backend=hit[1], cached=True)

        states = self._load()
        attempts: list[Attempt] = []
        throttled: list[str] = []
        try:
            for name in self.order:
                state = states[name]
                now = self.clock()
                if state.blocked_until > now:
                    attempts.append(Attempt(name, "cooling", detail=f"{state.blocked_until - now:.0f}s left"))
                    continue
                if now - state.last_call < self.min_interval:
                    attempts.append(Attempt(name, "throttled"))
                    throttled.append(name)
                    continue
                attempt = await self._try(name, client, query, limit, state)
                attempts.append(attempt)
                if attempt.outcome == "ok":
                    return self._remember(key, name, attempt, attempts)
            # Every untouched backend was merely called too recently: wait for the first and retry.
            for name in throttled:
                state = states[name]
                await self.sleep(max(0.0, state.last_call + self.min_interval - self.clock()))
                attempt = await self._try(name, client, query, limit, state)
                attempts.append(attempt)
                if attempt.outcome == "ok":
                    return self._remember(key, name, attempt, attempts)
            return SearchOutcome(items=[], attempts=attempts)
        finally:
            self._save(states)

    def _remember(self, key, name: str, attempt: Attempt, attempts: list[Attempt]) -> SearchOutcome:
        items = attempt.items  # type: ignore[attr-defined]
        if self.cache_ttl > 0:
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
            self._cache[key] = (self.clock() + self.cache_ttl, name, list(items))
        return SearchOutcome(items=items, backend=name, attempts=attempts)
