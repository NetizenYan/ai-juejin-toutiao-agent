import asyncio
import unittest


api_reranker = __import__("harness.reranker_api", fromlist=["reranker_api"])


class SiliconFlowApiRerankerTests(unittest.TestCase):
    def _items(self):
        return [
            {"id": "a", "title": "A title", "summary": "less relevant", "score": 0.9},
            {"id": "b", "title": "B title", "summary": "most relevant", "score": 0.8},
        ]

    def test_rerank_with_api_orders_items_and_records_scores(self):
        captured = {}

        def fake_transport(url, headers, payload, timeout):
            captured.update({
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout": timeout,
            })
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.42},
                ]
            }

        ranked, meta = asyncio.run(api_reranker.rerank_with_api(
            "most relevant",
            self._items(),
            top_k=2,
            api_key="test-key",
            model="Pro/BAAI/bge-reranker-v2-m3",
            transport=fake_transport,
        ))

        self.assertEqual([item["id"] for item in ranked], ["b", "a"])
        self.assertEqual(ranked[0]["rerank_score"], 0.91)
        self.assertEqual(ranked[0]["reranker_used"], "siliconflow_api")
        self.assertTrue(meta["used"])
        self.assertEqual(meta["reranker_used"], "siliconflow_api")
        self.assertEqual(captured["url"], "https://api.siliconflow.cn/v1/rerank")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["model"], "Pro/BAAI/bge-reranker-v2-m3")
        self.assertEqual(captured["payload"]["query"], "most relevant")
        self.assertEqual(len(captured["payload"]["documents"]), 2)
        self.assertIn("B title", captured["payload"]["documents"][1])

    def test_rerank_with_api_falls_back_without_exposing_api_key(self):
        def failing_transport(_url, _headers, _payload, _timeout):
            raise RuntimeError("service unavailable")

        ranked, meta = asyncio.run(api_reranker.rerank_with_api(
            "query",
            self._items(),
            top_k=2,
            api_key="secret-value",
            transport=failing_transport,
        ))

        self.assertEqual([item["id"] for item in ranked], ["a", "b"])
        self.assertFalse(meta["used"])
        self.assertEqual(meta["reranker_used"], "api_reranker_failed")
        self.assertIn("service unavailable", meta["reason"])
        self.assertNotIn("secret-value", repr(meta))


if __name__ == "__main__":
    unittest.main()
