import unittest
from types import SimpleNamespace

from mcp_servers import rag_server


class _FakeEmbeddingClient:
    class embeddings:
        @staticmethod
        async def create(model, input):  # noqa: ANN001
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 1024)])


class _FakeQdrant:
    async def query_points(self, **_kwargs):
        point = SimpleNamespace(
            score=0.88,
            payload={
                "news_id": 101,
                "chunk_index": 0,
                "title": "人工智能产业进展",
                "chunk_text": "人工智能产业有新进展。",
                "publish_ts": 0,
                "source": "新华社",
            },
        )
        return SimpleNamespace(points=[point])


class RagMcpRouteContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_news_uses_v2_when_search_version_is_v2(self):
        original_settings = rag_server.settings
        original_v1 = rag_server.search_news_rag
        original_v2 = getattr(rag_server, "search_news_rag_v2", None)
        calls = []

        async def fake_v1(*_args, **_kwargs):
            calls.append("v1")
            return {"tool": "retrieve_news", "index_version": "v1", "items": []}

        async def fake_v2(*_args, **_kwargs):
            calls.append("v2")
            return {"tool": "retrieve_news", "index_version": "v2_unified", "items": []}

        rag_server.settings = SimpleNamespace(rag_search_version="v2")
        rag_server.search_news_rag = fake_v1
        rag_server.search_news_rag_v2 = fake_v2
        try:
            result = await rag_server.retrieve_news("新质生产力", limit=5)
        finally:
            rag_server.settings = original_settings
            rag_server.search_news_rag = original_v1
            if original_v2 is None:
                delattr(rag_server, "search_news_rag_v2")
            else:
                rag_server.search_news_rag_v2 = original_v2

        self.assertEqual(calls, ["v2"])
        self.assertEqual(result["index_version"], "v2_unified")

    async def test_retrieve_news_includes_rag_route(self):
        original_embedding = rag_server.get_embedding_client
        original_qdrant = rag_server.get_qdrant
        original_assert_meta = rag_server.assert_meta_matches
        rag_server.get_embedding_client = lambda: _FakeEmbeddingClient()
        rag_server.get_qdrant = lambda: _FakeQdrant()
        rag_server.assert_meta_matches = lambda _model, _dim: None
        try:
            result = await rag_server.retrieve_news("这条新闻具体内容说了什么", limit=5)
        finally:
            rag_server.get_embedding_client = original_embedding
            rag_server.get_qdrant = original_qdrant
            rag_server.assert_meta_matches = original_assert_meta

        self.assertEqual(result.get("tool"), "retrieve_news")
        self.assertIn("rag_route", result)
        self.assertEqual(result["rag_route"]["query_type"], "content_detail")
        self.assertEqual(result["rag_route"]["retrieval_strategy"], "summary_with_body_fallback")
        self.assertEqual(result["rag_route"]["body_fallback_slots"], 1)


if __name__ == "__main__":
    unittest.main()
