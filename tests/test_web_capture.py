import asyncio
import hashlib
import inspect
import unittest

from harness.safe_http_client import SafeHttpError
from harness.web_capture import PlaywrightScreenshotBackend, WebScreenshotProvider, _html_snapshot


def public_resolver(_host, port, **_kwargs):
    return [(None, None, None, None, ("93.184.216.34", port))]


class FakeScreenshotBackend:
    def __init__(self):
        self.calls = []

    async def capture(self, *, url, output_path, viewport, timeout_ms, allowed_domains, blocked_domains, resolver):
        self.calls.append({
            "url": url,
            "output_path": output_path,
            "viewport": viewport,
            "timeout_ms": timeout_ms,
            "allowed_domains": allowed_domains,
            "blocked_domains": blocked_domains,
            "resolver": resolver,
        })
        output_path.write_bytes(b"fake-png-bytes")
        return {"final_url": url, "status_code": 200}


class WebCaptureTests(unittest.TestCase):
    def test_provider_captures_page_screenshot_with_hash_metadata(self):
        backend = FakeScreenshotBackend()
        provider = WebScreenshotProvider(
            backend=backend,
            output_dir="work/test_web_capture",
            resolver=public_resolver,
            clock=lambda: "2026-06-24T12:00:00Z",
        )

        result = asyncio.run(provider.capture("https://example.com/news"))

        expected_hash = "sha256:" + hashlib.sha256(b"fake-png-bytes").hexdigest()
        self.assertEqual(result["tool"], "web_capture")
        self.assertEqual(result["url"], "https://example.com/news")
        self.assertEqual(result["final_url"], "https://example.com/news")
        self.assertEqual(result["raw_image_hash"], expected_hash)
        self.assertEqual(result["captured_at"], "2026-06-24T12:00:00Z")
        self.assertTrue(result["image_path"].endswith(".png"))
        self.assertEqual(backend.calls[0]["viewport"], {"width": 1280, "height": 1600})

    def test_provider_rejects_unsafe_url_before_browser_backend_runs(self):
        backend = FakeScreenshotBackend()
        provider = WebScreenshotProvider(backend=backend, resolver=public_resolver)

        with self.assertRaises(SafeHttpError):
            asyncio.run(provider.capture("file:///etc/passwd"))

        self.assertEqual(backend.calls, [])

    def test_playwright_backend_does_not_let_browser_resolve_user_url_directly(self):
        source = inspect.getsource(PlaywrightScreenshotBackend.capture)

        self.assertIn("safe_fetch", source)
        self.assertIn("set_content", source)
        self.assertNotIn("route.continue_", source)
        self.assertNotIn("page.goto(", source)

    def test_html_snapshot_uses_render_char_limit_separate_from_fetch_limit(self):
        snapshot = _html_snapshot(
            b"<html><body><p>alpha beta gamma delta</p></body></html>",
            content_type="text/html; charset=utf-8",
            final_url="https://example.com/news",
            render_max_chars=12,
        )

        self.assertIn("alpha beta g", snapshot)
        self.assertNotIn("delta", snapshot)


if __name__ == "__main__":
    unittest.main()
