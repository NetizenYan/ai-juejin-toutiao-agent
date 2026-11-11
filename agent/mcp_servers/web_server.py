"""Web MCP server with safe HTTP guardrails."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict
from html.parser import HTMLParser
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from agent.config.ai_conf import settings
from agent.harness.external_evidence import ingest_url_via_ocr
from agent.harness.ocr_providers import create_ocr_provider
from agent.harness.safe_http_client import SafeHttpError, _check_domain_policy, safe_fetch
from agent.harness.web_capture import create_web_screenshot_provider, source_name_from_url
from agent.harness.web_search_router import SearchBlocked, WebSearchRouter, looks_blocked

mcp = FastMCP("toutiao-web")
_OCR_PROVIDER_CACHE: dict[str, object] = {}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join((data or "").split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


def _decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip().lower()
        if part.startswith("charset="):
            charset = part.split("=", 1)[1] or "utf-8"
    return body.decode(charset, errors="replace")


def _to_text(body: bytes, content_type: str) -> str:
    text = _decode_body(body, content_type)
    if "html" not in content_type.lower():
        return text
    parser = _TextExtractor()
    parser.feed(text)
    return parser.text()


def _ocr_provider_cache_key(provider_name: str | None = None) -> str:
    value = (provider_name or settings.ocr_provider_name or "paddleocr").strip()
    return value.lower().replace("-", "_") or "paddleocr"


def _get_ocr_provider(provider_name: str | None = None):
    key = _ocr_provider_cache_key(provider_name)
    provider = _OCR_PROVIDER_CACHE.get(key)
    if provider is None:
        kwargs = {"enable_mkldnn": settings.ocr_enable_mkldnn} if key in {"paddle", "paddleocr", "paddle_ocr", "default"} else {}
        provider = create_ocr_provider(key, **kwargs)
        _OCR_PROVIDER_CACHE[key] = provider
    return provider


@mcp.tool()
async def web_fetch(url: str) -> dict:
    """Fetch one allowlisted public http(s) URL through safe_http_client."""
    try:
        response = await safe_fetch(
            url,
            max_bytes=settings.max_fetch_bytes,
            timeout=settings.tool_timeout_seconds,
            max_redirects=settings.max_redirects,
            allowed_domains=settings.web_allowed_domains_list,
            blocked_domains=settings.web_blocked_domains_list,
        )
    except SafeHttpError as exc:
        return {"tool": "web_fetch", "url": url, "error": str(exc), "evidence_ids": []}

    content_type = response.headers.get("content-type", "")
    text = _to_text(response.body, content_type)
    excerpt = text[:4000].strip()
    return {
        "tool": "web_fetch",
        "url": url,
        "final_url": response.final_url,
        "status_code": response.status_code,
        "content_type": content_type,
        "text": excerpt,
        "evidence_ids": [f"web:{response.final_url}"],
    }


def _web_search_provider() -> str:
    if settings.web_search_provider:
        return settings.web_search_provider
    if settings.web_search_base_url:
        return "searxng"
    return "tavily" if settings.web_search_api_key else ""


def _host_allowed(url: str) -> bool:
    host = urlsplit(url or "").hostname or ""
    if not host:
        return False
    try:
        _check_domain_policy(host, settings.web_allowed_domains_list, settings.web_blocked_domains_list)
    except SafeHttpError:
        return False
    return True


_SEARXNG_ENGINES: dict[str, tuple[float, frozenset[str]]] = {}
_SEARXNG_ENGINES_TTL_SECONDS = 600


async def _searxng_engines(client) -> frozenset[str]:
    """Enabled SearXNG engines in the searched categories, from its /config (cached for a while)."""
    base = settings.web_search_base_url
    cached = _SEARXNG_ENGINES.get(base)
    if cached and cached[0] > time.time():
        return cached[1]
    wanted = {item.strip() for item in settings.web_search_categories.split(",") if item.strip()}
    try:
        resp = await client.get(f"{base}/config")
        resp.raise_for_status()
        engines = frozenset(
            e["name"] for e in (resp.json().get("engines") or [])
            if e.get("enabled") and wanted & set(e.get("categories") or [])
        )
    except Exception:  # noqa: BLE001 - without the list nothing is called blocked; empty streaks still cool it down
        return frozenset()
    _SEARXNG_ENGINES[base] = (time.time() + _SEARXNG_ENGINES_TTL_SECONDS, engines)
    return engines


async def _search_searxng(client, query: str, limit: int) -> list[dict]:
    # 自部署 SearXNG（配置里的固定端点，不是用户可控 URL，故直连）；需在其 settings.yml 打开 json 格式。
    resp = await client.get(
        f"{settings.web_search_base_url}/search",
        params={
            "q": query, "format": "json", "categories": settings.web_search_categories,
            "language": settings.web_search_language, "safesearch": 1,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    results = body.get("results") or []
    if not results:
        # 上游引擎被拦时 SearXNG 仍返回 200，只在 unresponsive_engines 里写 CAPTCHA / Suspended。
        # 只有启用的引擎全都被拦才算 SearXNG 被拦；还有引擎正常应答却没结果，就只是“没搜到”。
        unresponsive = {name: reason for name, reason in (body.get("unresponsive_engines") or [])}
        enabled = await _searxng_engines(client)
        if enabled and enabled <= set(unresponsive):
            down = "; ".join(f"{name}: {unresponsive[name]}" for name in sorted(enabled))
            if all(looks_blocked(unresponsive[name]) for name in enabled):
                raise SearchBlocked(down)
            raise RuntimeError(down)
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "summary": (r.get("content") or "")[:300],
            "published": r.get("publishedDate"),
            "engine": r.get("engine"),
        }
        for r in results
    ]


_BAIDU_LINK_HOSTS = {"www.baidu.com", "baidu.com"}


async def _resolve_baidu_link(client, url: str) -> str:
    """百度结果是 baidu.com/link 跳转链接；取出真实网址，域名过滤和引用才有意义。失败时保留原链接。"""
    parts = urlsplit(url)
    if parts.hostname not in _BAIDU_LINK_HOSTS or not parts.path.startswith("/link"):
        return url
    try:
        resp = await client.get(url, follow_redirects=False, timeout=5)
    except Exception:  # noqa: BLE001
        return url
    location = resp.headers.get("location") or ""
    if not location:
        match = re.search(r"""URL='?([^'"\s>]+)""", resp.text or "")
        location = match.group(1) if match else ""
    return location if location.startswith(("http://", "https://")) else url


async def _search_open_websearch(client, query: str, limit: int) -> list[dict]:
    # 本机 open-websearch daemon（固定端点）。被拦时它仍回 status=ok，原因写在 partialFailures 里。
    resp = await client.post(
        f"{settings.open_websearch_url}/search",
        json={"query": query, "limit": limit, "engines": list(settings.open_websearch_engines)},
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "ok":
        raise RuntimeError(str(body.get("error") or body.get("hint") or "open-websearch error"))
    data = body.get("data") or {}
    results = data.get("results") or []
    if not results:
        failures = "; ".join(
            f"{f.get('engine')}: {f.get('message') or f.get('code')}" for f in (data.get("partialFailures") or [])
        )
        if failures and looks_blocked(failures):
            raise SearchBlocked(failures)
        if failures:
            raise RuntimeError(failures)
    urls = await asyncio.gather(*(_resolve_baidu_link(client, r.get("url") or "") for r in results))
    return [
        {
            "title": r.get("title"),
            "url": url,
            "summary": (r.get("description") or "")[:300],
            "site": r.get("source") or None,
            "engine": r.get("engine"),
        }
        for r, url in zip(results, urls)
    ]


async def _search_tavily(client, query: str, limit: int) -> list[dict]:
    # Tavily（固定可信端点；非用户可控 URL，故直连）。429 / 432 / 433 是限流或额度用完。
    resp = await client.post(
        "https://api.tavily.com/search",
        json={"api_key": settings.web_search_api_key, "query": query, "max_results": limit},
    )
    if resp.status_code in {429, 432, 433}:
        raise SearchBlocked(f"tavily HTTP {resp.status_code}")
    resp.raise_for_status()
    return [
        {"title": r.get("title"), "url": r.get("url"), "summary": (r.get("content") or "")[:300]}
        for r in (resp.json().get("results") or [])
    ]


_SEARCH_PROVIDERS = {"openwebsearch": _search_open_websearch, "searxng": _search_searxng, "tavily": _search_tavily}


def _configured_backends() -> list[str]:
    ready = {
        "openwebsearch": bool(settings.open_websearch_url),
        "searxng": bool(settings.web_search_base_url),
        "tavily": bool(settings.web_search_api_key),
    }
    order = list(settings.web_search_backends) or [_web_search_provider()]
    return [name for name in order if ready.get(name)]


_ROUTER: tuple[object, WebSearchRouter] | None = None


def _router() -> WebSearchRouter:
    """One router per settings object, so its cache and breaker survive between calls."""
    global _ROUTER
    if _ROUTER is None or _ROUTER[0] is not settings:
        _ROUTER = (settings, WebSearchRouter(
            _SEARCH_PROVIDERS,
            _configured_backends(),
            state_path=settings.web_search_state_path,
            block_cooldown=settings.web_search_block_cooldown_seconds,
            block_cooldown_max=settings.web_search_block_cooldown_max_seconds,
            min_interval=settings.web_search_min_interval_seconds,
            cache_ttl=settings.web_search_cache_ttl_seconds,
            keep_item=lambda item: _host_allowed(item.get("url") or ""),
        ))
    return _ROUTER[1]


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> dict:
    """联网搜索：按 WEB_SEARCH_BACKENDS 顺序尝试 open-websearch（百度）、SearXNG、Tavily，被拦自动切换。

    结果只是站外候选：按 WEB_ALLOWED_DOMAINS / WEB_BLOCKED_DOMAINS 过滤，链接应再经 web_fetch 抓取，不直接信任摘要。
    给模型看的 note / error 不带配置细节，排查信息放在以 _ 开头的字段里（不会进入回答过滤的文本）。
    """
    limit = max(1, min(int(limit), 10))
    router = _router()
    if not router.order:
        return {
            "tool": "web_search",
            "items": [],
            "evidence_ids": [],
            "note": "联网搜索暂不可用。",
            "_setup_hint": "设置 OPEN_WEBSEARCH_URL、WEB_SEARCH_BASE_URL（SearXNG）或 WEB_SEARCH_API_KEY（Tavily）后启用。",
        }

    import httpx
    async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds) as client:
        outcome = await router.search(client, query, limit)

    result = {
        "tool": "web_search",
        "items": outcome.items,
        "evidence_ids": [f"web:{it['url']}" for it in outcome.items],
        "_backend": outcome.backend,
        "_cached": outcome.cached,
        "_attempts": [asdict(a) for a in outcome.attempts],
    }
    if outcome.failed:
        result["error"] = "联网搜索暂时失败。"
    elif not outcome.items:
        result["note"] = (
            "联网搜索没有找到相关结果（部分搜索源暂时不可用）。" if outcome.incomplete else "联网搜索没有找到相关结果。"
        )
    return result


@mcp.tool()
async def web_capture_ocr(url: str, source_name: str = "", min_ocr_confidence: float = 0.35) -> dict:
    """Capture an external webpage screenshot, run OCR, and stage it as low-trust evidence."""
    threshold = max(0.0, min(float(min_ocr_confidence), 1.0))
    try:
        screenshot_provider = create_web_screenshot_provider()
        ocr_provider = _get_ocr_provider(settings.ocr_provider_name)
        item = await ingest_url_via_ocr(
            url,
            source_name=(source_name or source_name_from_url(url)),
            capture_screenshot_fn=screenshot_provider.capture,
            ocr_provider=ocr_provider,
            min_ocr_confidence=threshold,
            index_enabled=settings.external_doc_indexing_enabled,
        )
    except (SafeHttpError, RuntimeError, ValueError) as exc:
        return {"tool": "web_capture_ocr", "url": url, "error": str(exc), "evidence_ids": []}
    except Exception as exc:  # noqa: BLE001 - external capture/OCR must fail closed
        return {"tool": "web_capture_ocr", "url": url, "error": str(exc), "evidence_ids": []}

    evidence_id = item.get("evidence_id")
    return {
        "tool": "web_capture_ocr",
        "url": url,
        "final_url": item.get("source_url") or url,
        "item": item,
        "evidence_ids": [evidence_id] if evidence_id else [],
    }


if __name__ == "__main__":
    mcp.run()
