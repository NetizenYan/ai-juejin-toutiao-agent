"""Guarded webpage screenshot capture for OCR ingestion."""
from __future__ import annotations

import html
from html.parser import HTMLParser
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from config.ai_conf import settings
from harness.safe_http_client import Resolver, safe_fetch, safe_resolve


ClockFn = Callable[[], str]


class ScreenshotBackend(Protocol):
    async def capture(
        self,
        *,
        url: str,
        output_path: Path,
        viewport: dict[str, int],
        timeout_ms: int,
        allowed_domains: tuple[str, ...],
        blocked_domains: tuple[str, ...],
        resolver: Resolver | None,
    ) -> dict[str, Any]:
        """Write a screenshot to output_path and return browser metadata."""


@dataclass(frozen=True)
class WebScreenshotResult:
    url: str
    final_url: str
    image_path: str
    raw_image_hash: str
    captured_at: str
    status_code: int | None = None
    provider: str = "playwright"

    def as_payload(self) -> dict[str, Any]:
        return {
            "tool": "web_capture",
            "url": self.url,
            "final_url": self.final_url,
            "image_path": self.image_path,
            "raw_image_hash": self.raw_image_hash,
            "captured_at": self.captured_at,
            "status_code": self.status_code,
            "provider": self.provider,
        }


class PlaywrightScreenshotBackend:
    """Playwright-backed screenshot backend.

    The browser renders a safe, local text snapshot. It never resolves or
    connects to the user-supplied URL directly; network I/O stays in safe_fetch.
    """

    async def capture(
        self,
        *,
        url: str,
        output_path: Path,
        viewport: dict[str, int],
        timeout_ms: int,
        allowed_domains: tuple[str, ...],
        blocked_domains: tuple[str, ...],
        resolver: Resolver | None,
    ) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install playwright and run `playwright install chromium` "
                "in the web capture runtime."
            ) from exc

        response = await safe_fetch(
            url,
            max_bytes=settings.max_fetch_bytes,
            timeout=max(1, timeout_ms // 1000),
            max_redirects=settings.max_redirects,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            resolver=resolver,
        )
        snapshot_html = _html_snapshot(
            response.body,
            content_type=response.headers.get("content-type", ""),
            final_url=response.final_url,
            render_max_chars=settings.web_capture_render_max_chars,
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport=viewport)

                async def abort_network(route, request):  # noqa: ARG001
                    await route.abort()

                await page.route("**/*", abort_network)
                await page.set_content(snapshot_html, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.screenshot(path=str(output_path), full_page=True)
                return {
                    "final_url": response.final_url,
                    "status_code": response.status_code,
                }
            finally:
                await browser.close()


class WebScreenshotProvider:
    def __init__(
        self,
        *,
        backend: ScreenshotBackend | None = None,
        output_dir: str | Path = "work/web_captures",
        viewport_width: int = 1280,
        viewport_height: int = 1600,
        timeout_seconds: int = 30,
        allowed_domains: tuple[str, ...] | list[str] | None = None,
        blocked_domains: tuple[str, ...] | list[str] | None = None,
        resolver: Resolver | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self.backend = backend or PlaywrightScreenshotBackend()
        self.output_dir = Path(output_dir)
        self.viewport = {"width": int(viewport_width), "height": int(viewport_height)}
        self.timeout_seconds = int(timeout_seconds)
        self.allowed_domains = tuple(allowed_domains or ())
        self.blocked_domains = tuple(blocked_domains or ())
        self.resolver = resolver
        self.clock = clock or _utc_now_iso

    async def capture(self, url: str) -> dict[str, Any]:
        safe_resolve(
            url,
            resolver=self.resolver,
            allowed_domains=self.allowed_domains,
            blocked_domains=self.blocked_domains,
        )
        captured_at = self.clock()
        output_path = self._output_path(url, captured_at)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        browser_result = await self.backend.capture(
            url=url,
            output_path=output_path,
            viewport=dict(self.viewport),
            timeout_ms=self.timeout_seconds * 1000,
            allowed_domains=self.allowed_domains,
            blocked_domains=self.blocked_domains,
            resolver=self.resolver,
        )
        if not output_path.exists():
            raise RuntimeError("Screenshot backend did not create an image file.")

        result = WebScreenshotResult(
            url=url,
            final_url=str(browser_result.get("final_url") or url),
            image_path=str(output_path),
            raw_image_hash=_hash_file(output_path),
            captured_at=captured_at,
            status_code=browser_result.get("status_code"),
        )
        return result.as_payload()

    def _output_path(self, url: str, captured_at: str) -> Path:
        day = captured_at[:10].replace("-", "") or "capture"
        digest = hashlib.sha256(f"{url}|{captured_at}".encode("utf-8")).hexdigest()[:24]
        return self.output_dir / day / f"{digest}.png"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip() or charset
            break
    return body.decode(charset, errors="replace")


def _visible_text_from_html(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    return "\n".join(parser.parts)


def _html_snapshot(
    body: bytes,
    *,
    content_type: str,
    final_url: str,
    render_max_chars: int | None = None,
) -> str:
    decoded = _decode_body(body, content_type)
    if "html" in content_type.lower():
        visible = _visible_text_from_html(decoded) or decoded
    else:
        visible = decoded
    limit = max(1, int(render_max_chars if render_max_chars is not None else settings.web_capture_render_max_chars))
    safe_text = html.escape(visible[:limit])
    safe_url = html.escape(final_url)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<style>"
        "body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:32px;line-height:1.6;color:#111;background:#fff;}"
        ".source{font-size:14px;color:#555;margin-bottom:24px;word-break:break-all;}"
        "pre{white-space:pre-wrap;word-break:break-word;font-size:18px;}"
        "</style></head><body>"
        f"<div class=\"source\">Source: {safe_url}</div><pre>{safe_text}</pre>"
        "</body></html>"
    )


def source_name_from_url(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if "reuters.com" in host:
        return "Reuters"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "X"
    if "instagram.com" in host:
        return "Instagram"
    if host.startswith("www."):
        host = host[4:]
    return host or "web"


def create_web_screenshot_provider() -> WebScreenshotProvider:
    return WebScreenshotProvider(
        output_dir=settings.web_capture_output_dir,
        viewport_width=settings.web_capture_viewport_width,
        viewport_height=settings.web_capture_viewport_height,
        timeout_seconds=settings.tool_timeout_seconds,
        allowed_domains=settings.web_allowed_domains,
        blocked_domains=settings.web_blocked_domains,
    )


__all__ = [
    "PlaywrightScreenshotBackend",
    "WebScreenshotProvider",
    "WebScreenshotResult",
    "create_web_screenshot_provider",
    "source_name_from_url",
]
