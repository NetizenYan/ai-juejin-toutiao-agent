"""web_search backends (open-websearch, SearXNG, Tavily), their block signals, and safe degradation."""
import asyncio
import unittest
from dataclasses import replace
from unittest import mock

import httpx

from agent.mcp_servers import web_server


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=None)

    def json(self):
        return self._payload


class _FakeClient:
    """Routes each request through `handler(method, url, body)`, which returns a _FakeResponse."""

    calls: list[tuple] = []
    handler = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, **kwargs):
        return self._respond("GET", url, params)

    async def post(self, url, json=None, **kwargs):
        return self._respond("POST", url, json)

    def _respond(self, method, url, body):
        type(self).calls.append((method, url, body))
        outcome = type(self).handler(method, url, body)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _search(settings, handler, query="神舟三号 推迟发射", limit=5):
    _FakeClient.calls, _FakeClient.handler = [], staticmethod(handler)
    web_server._ROUTER = None  # a fresh breaker and cache per test
    with mock.patch.object(web_server, "settings", settings), mock.patch.object(httpx, "AsyncClient", _FakeClient):
        return asyncio.run(web_server.web_search(query, limit))


BASE = replace(
    web_server.settings,
    web_search_provider="",
    web_search_backends=(),
    web_search_base_url="",
    web_search_api_key="",
    open_websearch_url="",
    open_websearch_engines=("baidu",),
    web_search_language="zh-CN",
    web_search_categories="general",
    web_allowed_domains=(),
    web_blocked_domains=(),
    web_search_state_path="",
    web_search_min_interval_seconds=0,
    web_search_cache_ttl_seconds=0,
)
SEARXNG = replace(BASE, web_search_base_url="http://127.0.0.1:8889")
BOTH = replace(
    BASE,
    web_search_backends=("openwebsearch", "searxng"),
    open_websearch_url="http://127.0.0.1:3210",
    web_search_base_url="http://127.0.0.1:8889",
)


def _searxng_ok(*urls):
    return _FakeResponse({"results": [{"title": u, "url": u, "content": "c", "engine": "360search"} for u in urls]})


def _owse(results=(), failures=()):
    return _FakeResponse({"status": "ok", "data": {"results": list(results), "partialFailures": list(failures)}})


class SearxngTests(unittest.TestCase):
    def test_base_url_selects_searxng_and_maps_results(self):
        payload = {"results": [
            {"title": "神舟三号推迟发射", "url": "https://www.news.cn/a", "content": "因插头问题推迟" * 50,
             "publishedDate": "2002-03-25T00:00:00", "engine": "360search"},
        ]}

        result = _search(SEARXNG, lambda m, u, b: _FakeResponse(payload))

        method, url, params = _FakeClient.calls[0]
        self.assertEqual((method, url), ("GET", "http://127.0.0.1:8889/search"))
        self.assertEqual((params["format"], params["language"], params["categories"]), ("json", "zh-CN", "general"))
        item = result["items"][0]
        self.assertEqual(item["url"], "https://www.news.cn/a")
        self.assertLessEqual(len(item["summary"]), 300)
        self.assertEqual(result["evidence_ids"], ["web:https://www.news.cn/a"])
        self.assertEqual(result["_backend"], "searxng")

    def test_searxng_is_blocked_only_when_every_enabled_engine_is(self):
        def handler(unresponsive):
            def respond(method, url, body):
                if url.endswith("/config"):
                    return _FakeResponse({"engines": [
                        {"name": "baidu", "enabled": True, "categories": ["general"]},
                        {"name": "360search", "enabled": True, "categories": ["general"]},
                        {"name": "bing news", "enabled": True, "categories": ["news"]},
                    ]})
                return _FakeResponse({"results": [], "unresponsive_engines": unresponsive})
            return respond

        web_server._SEARXNG_ENGINES.clear()
        all_down = _search(SEARXNG, handler([["baidu", "CAPTCHA"], ["360search", "Suspended: CAPTCHA"]]))
        web_server._SEARXNG_ENGINES.clear()
        one_left = _search(SEARXNG, handler([["baidu", "CAPTCHA"]]))

        self.assertEqual(all_down["_attempts"][0]["outcome"], "blocked")
        self.assertEqual(all_down["error"], "联网搜索暂时失败。")
        self.assertEqual(one_left["_attempts"][0]["outcome"], "empty")
        self.assertNotIn("error", one_left)
        self.assertEqual(one_left["note"], "联网搜索没有找到相关结果。")

    def test_nothing_found_while_another_source_is_down_says_so(self):
        def handler(method, url, body):
            if url.startswith("http://127.0.0.1:3210"):
                return _owse(failures=[{"engine": "baidu", "message": "security verification"}])
            return _FakeResponse({"results": []})

        result = _search(BOTH, handler)

        self.assertNotIn("error", result)
        self.assertEqual(result["note"], "联网搜索没有找到相关结果（部分搜索源暂时不可用）。")

    def test_allowlist_keeps_only_listed_sites(self):
        settings = replace(SEARXNG, web_allowed_domains=("news.cn",))

        result = _search(settings, lambda m, u, b: _searxng_ok("https://www.news.cn/1", "https://blog.example/2"))

        self.assertEqual([it["url"] for it in result["items"]], ["https://www.news.cn/1"])


class OpenWebsearchTests(unittest.TestCase):
    def test_baidu_links_are_resolved_to_the_real_site(self):
        link = "http://www.baidu.com/link?url=abc"

        def handler(method, url, body):
            if url.endswith("/search"):
                self.assertEqual(body["engines"], ["baidu"])
                return _owse([{"title": "神舟三号", "url": link, "description": "插头", "source": "新华网", "engine": "baidu"}])
            return _FakeResponse(status_code=302, headers={"location": "https://www.news.cn/2002/a.htm"})

        result = _search(replace(BOTH, web_search_backends=("openwebsearch",)), handler)

        self.assertEqual(result["items"][0]["url"], "https://www.news.cn/2002/a.htm")
        self.assertEqual(result["items"][0]["site"], "新华网")
        self.assertEqual(result["_backend"], "openwebsearch")

    def test_unresolvable_baidu_link_is_kept(self):
        link = "http://www.baidu.com/link?url=abc"

        def handler(method, url, body):
            if url.endswith("/search"):
                return _owse([{"title": "t", "url": link, "description": "d", "engine": "baidu"}])
            return httpx.ConnectError("timeout")

        result = _search(replace(BOTH, web_search_backends=("openwebsearch",)), handler)

        self.assertEqual(result["items"][0]["url"], link)

    def test_baidu_verification_page_switches_to_searxng(self):
        def handler(method, url, body):
            if url.startswith("http://127.0.0.1:3210"):
                return _owse(failures=[{"engine": "baidu", "message": "Baidu redirected to a security verification page"}])
            return _searxng_ok("https://www.news.cn/1")

        result = _search(BOTH, handler)

        self.assertEqual([a["outcome"] for a in result["_attempts"]], ["blocked", "ok"])
        self.assertEqual(result["_backend"], "searxng")
        self.assertNotIn("error", result)

    def test_daemon_down_switches_to_searxng(self):
        def handler(method, url, body):
            if url.startswith("http://127.0.0.1:3210"):
                return httpx.ConnectError("connection refused")
            return _searxng_ok("https://www.news.cn/1")

        result = _search(BOTH, handler)

        self.assertEqual([a["outcome"] for a in result["_attempts"]], ["error", "ok"])


class ProviderSelectionTests(unittest.TestCase):
    def test_key_without_base_url_uses_tavily(self):
        settings = replace(BASE, web_search_api_key="k")

        _search(settings, lambda m, u, b: _FakeResponse({"results": [{"title": "t", "url": "https://www.news.cn/t", "content": "c"}]}))

        self.assertEqual(_FakeClient.calls[0][:2], ("POST", "https://api.tavily.com/search"))

    def test_tavily_quota_is_a_block(self):
        result = _search(replace(BASE, web_search_api_key="k"), lambda m, u, b: _FakeResponse(status_code=432))

        self.assertEqual(result["_attempts"][0]["outcome"], "blocked")

    def test_backends_without_config_are_skipped(self):
        settings = replace(BOTH, open_websearch_url="")

        result = _search(settings, lambda m, u, b: _searxng_ok("https://www.news.cn/1"))

        self.assertEqual([a["backend"] for a in result["_attempts"]], ["searxng"])

    def test_backends_none_turns_web_search_off_for_evaluation(self):
        settings = replace(BOTH, web_search_backends=("none",), web_search_api_key="k")

        result = _search(settings, lambda m, u, b: self.fail("no request expected"))

        self.assertEqual(result["note"], "联网搜索暂不可用。")

    def test_unconfigured_search_does_not_tell_the_model_about_keys(self):
        result = _search(BASE, lambda m, u, b: self.fail("no request expected"))

        self.assertEqual(result["items"], [])
        self.assertNotIn("KEY", result["note"])
        self.assertNotIn("密钥", result["note"])

    def test_failure_hides_the_endpoint_from_the_model(self):
        result = _search(SEARXNG, lambda m, u, b: httpx.ConnectError("connect to http://127.0.0.1:8889 failed"))

        self.assertNotIn("127.0.0.1", result["error"])
        self.assertIn("127.0.0.1", result["_attempts"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
