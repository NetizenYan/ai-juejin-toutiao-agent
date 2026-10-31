"""web_search works against a self-hosted SearXNG as well as Tavily, and degrades without leaking config."""
import asyncio
import unittest
from dataclasses import replace
from unittest import mock

import httpx

from mcp_servers import web_server


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    calls: list[tuple] = []
    payload: dict = {}
    fail: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return self._respond(("GET", url, params))

    async def post(self, url, json=None):
        return self._respond(("POST", url, json))

    def _respond(self, call):
        type(self).calls.append(call)
        if type(self).fail:
            raise type(self).fail
        return _FakeResponse(type(self).payload)


def _search(settings, payload=None, fail=None, query="神舟三号 推迟发射", limit=5):
    _FakeClient.calls, _FakeClient.payload, _FakeClient.fail = [], payload or {}, fail
    with mock.patch.object(web_server, "settings", settings), mock.patch.object(httpx, "AsyncClient", _FakeClient):
        return asyncio.run(web_server.web_search(query, limit))


SEARXNG = replace(
    web_server.settings,
    web_search_provider="",
    web_search_base_url="http://127.0.0.1:8888",
    web_search_language="zh-CN",
    web_search_categories="general",
    web_search_api_key="",
    web_allowed_domains=(),
    web_blocked_domains=(),
)


class SearxngTests(unittest.TestCase):
    def test_base_url_selects_searxng_and_maps_results(self):
        payload = {"results": [
            {"title": "神舟三号推迟发射", "url": "https://www.news.cn/a", "content": "因插头问题推迟" * 50,
             "publishedDate": "2002-03-25T00:00:00", "engine": "bing"},
        ]}

        result = _search(SEARXNG, payload)

        method, url, params = _FakeClient.calls[0]
        self.assertEqual((method, url), ("GET", "http://127.0.0.1:8888/search"))
        self.assertEqual(params["format"], "json")
        self.assertEqual(params["language"], "zh-CN")
        self.assertEqual(params["categories"], "general")
        item = result["items"][0]
        self.assertEqual(item["url"], "https://www.news.cn/a")
        self.assertLessEqual(len(item["summary"]), 300)
        self.assertEqual(item["published"], "2002-03-25T00:00:00")
        self.assertEqual(result["evidence_ids"], ["web:https://www.news.cn/a"])

    def test_results_are_deduplicated_filtered_and_limited(self):
        payload = {"results": [
            {"title": "a", "url": "https://www.news.cn/1", "content": "x"},
            {"title": "a again", "url": "https://www.news.cn/1", "content": "x"},
            {"title": "blocked", "url": "https://spam.example/2", "content": "x"},
            {"title": "no url", "url": "", "content": "x"},
            {"title": "b", "url": "https://www.gov.cn/3", "content": "x"},
            {"title": "c", "url": "https://www.gov.cn/4", "content": "x"},
        ]}
        settings = replace(SEARXNG, web_blocked_domains=("spam.example",))

        result = _search(settings, payload, limit=2)

        self.assertEqual([it["url"] for it in result["items"]], ["https://www.news.cn/1", "https://www.gov.cn/3"])

    def test_allowlist_keeps_only_listed_sites(self):
        payload = {"results": [
            {"title": "a", "url": "https://www.news.cn/1", "content": "x"},
            {"title": "b", "url": "https://blog.example/2", "content": "x"},
        ]}

        result = _search(replace(SEARXNG, web_allowed_domains=("news.cn",)), payload)

        self.assertEqual([it["url"] for it in result["items"]], ["https://www.news.cn/1"])


class ProviderSelectionTests(unittest.TestCase):
    def test_key_without_base_url_uses_tavily(self):
        settings = replace(SEARXNG, web_search_base_url="", web_search_api_key="k")

        _search(settings, {"results": [{"title": "t", "url": "https://www.news.cn/t", "content": "c"}]})

        self.assertEqual(_FakeClient.calls[0][:2], ("POST", "https://api.tavily.com/search"))

    def test_unconfigured_search_does_not_tell_the_model_about_keys(self):
        result = _search(replace(SEARXNG, web_search_base_url="", web_search_api_key=""))

        self.assertEqual(_FakeClient.calls, [])
        self.assertEqual(result["items"], [])
        self.assertNotIn("KEY", result["note"])
        self.assertNotIn("密钥", result["note"])

    def test_failure_hides_the_endpoint_from_the_model(self):
        result = _search(SEARXNG, fail=httpx.ConnectError("connect to http://127.0.0.1:8888 failed"))

        self.assertNotIn("127.0.0.1", result["error"])
        self.assertIn("127.0.0.1", result["_detail"])


if __name__ == "__main__":
    unittest.main()
