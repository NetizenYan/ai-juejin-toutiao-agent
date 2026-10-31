"""Web MCP server with safe HTTP guardrails."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from config.ai_conf import settings
from harness.external_evidence import ingest_url_via_ocr
from harness.ocr_providers import create_ocr_provider
from harness.safe_http_client import SafeHttpError, _check_domain_policy, safe_fetch
from harness.web_capture import create_web_screenshot_provider, source_name_from_url

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


async def _search_searxng(client, query: str, limit: int) -> list[dict]:
    # 自部署 SearXNG（配置里的固定端点，不是用户可控 URL，故直连）；需在其 settings.yml 打开 json 格式。
    resp = await client.get(
        f"{settings.web_search_base_url}/search",
        params={"q": query, "format": "json", "language": settings.web_search_language, "safesearch": 1},
    )
    resp.raise_for_status()
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "summary": (r.get("content") or "")[:300],
            "published": r.get("publishedDate"),
            "engine": r.get("engine"),
        }
        for r in (resp.json().get("results") or [])
    ]


async def _search_tavily(client, query: str, limit: int) -> list[dict]:
    # Tavily（固定可信端点；非用户可控 URL，故直连）。
    resp = await client.post(
        "https://api.tavily.com/search",
        json={"api_key": settings.web_search_api_key, "query": query, "max_results": limit},
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title"), "url": r.get("url"), "summary": (r.get("content") or "")[:300]}
        for r in (resp.json().get("results") or [])
    ]


_SEARCH_PROVIDERS = {"searxng": _search_searxng, "tavily": _search_tavily}


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> dict:
    """联网搜索：自部署 SearXNG（WEB_SEARCH_BASE_URL）或 Tavily（WEB_SEARCH_API_KEY）；未配置则优雅降级。

    结果只是站外候选：按 WEB_ALLOWED_DOMAINS / WEB_BLOCKED_DOMAINS 过滤，链接应再经 web_fetch 抓取，不直接信任摘要。
    给模型看的 note / error 不带配置细节，排查信息放在以 _ 开头的字段里（不会进入回答过滤的文本）。
    """
    limit = max(1, min(int(limit), 10))
    search = _SEARCH_PROVIDERS.get(_web_search_provider())
    if search is None:
        return {
            "tool": "web_search",
            "items": [],
            "evidence_ids": [],
            "note": "联网搜索暂不可用。",
            "_setup_hint": "设置 WEB_SEARCH_BASE_URL（SearXNG）或 WEB_SEARCH_API_KEY（Tavily）后启用。",
        }

    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds) as client:
            raw = await search(client, query, limit)
    except Exception as exc:  # noqa: BLE001 - 搜索失败优雅降级
        return {"tool": "web_search", "items": [], "evidence_ids": [], "error": "联网搜索暂时失败。", "_detail": str(exc)}

    items, seen = [], set()
    for item in raw:
        url = item.get("url") or ""
        if url in seen or not _host_allowed(url):
            continue
        seen.add(url)
        items.append(item)
        if len(items) >= limit:
            break
    return {
        "tool": "web_search",
        "items": items,
        "evidence_ids": [f"web:{it['url']}" for it in items],
    }


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
