import asyncio
import os
import unittest
from unittest.mock import patch

from config.ai_conf import AISettings, normalize_b_v3_source_policy
from harness import reranker


class SiliconFlowModelStackTests(unittest.TestCase):
    def test_normalizes_b_v3_source_policy(self):
        self.assertEqual(normalize_b_v3_source_policy(None), "local_test")
        self.assertEqual(normalize_b_v3_source_policy(" REVIEW_SAFE "), "review_safe")
        self.assertEqual(normalize_b_v3_source_policy("strict"), "strict")
        with self.assertRaises(ValueError):
            normalize_b_v3_source_policy("unsafe_all")

    def test_siliconflow_key_can_feed_llm_and_embedding_clients(self):
        with patch.dict(
            os.environ,
            {
                "SILICONFLOW_API_KEY": "sf-test-key",
                "LLM_API_KEY": "",
                "EMBEDDING_API_KEY": "",
            },
            clear=False,
        ):
            settings = AISettings()

        self.assertEqual(settings.llm_api_key, "sf-test-key")
        self.assertEqual(settings.embedding_api_key, "sf-test-key")

    def test_llm_key_does_not_fallback_to_deepseek_for_siliconflow_stack(self):
        with patch.dict(
            os.environ,
            {
                "LLM_API_KEY": "",
                "SILICONFLOW_API_KEY": "",
                "DEEPSEEK_API_KEY": "deepseek-test-key",
            },
            clear=False,
        ):
            settings = AISettings()

        self.assertEqual(settings.llm_api_key, "ollama")

    def test_rerank_uses_api_provider_when_enabled(self):
        items = [
            {"id": "a", "title": "A", "summary": "less relevant"},
            {"id": "b", "title": "B", "summary": "most relevant"},
        ]
        calls = []

        async def fake_api_rerank(query, candidates, top_k=5, **kwargs):
            calls.append({
                "query": query,
                "top_k": top_k,
                "model": kwargs.get("model"),
            })
            return [dict(candidates[1], rerank_score=0.9), dict(candidates[0], rerank_score=0.1)], {
                "used": True,
                "reranker_used": "siliconflow_api",
            }

        with patch.dict(
            os.environ,
            {
                "RERANKER_PROVIDER": "api",
                "RERANKER_API_MODEL": "Pro/BAAI/bge-reranker-v2-m3",
            },
            clear=False,
        ):
            with patch.object(reranker, "rerank_with_api", fake_api_rerank, create=True):
                ranked = asyncio.run(reranker.rerank("most relevant", items, top_k=2))

        self.assertEqual([item["id"] for item in ranked], ["b", "a"])
        self.assertEqual(calls, [{
            "query": "most relevant",
            "top_k": 2,
            "model": "Pro/BAAI/bge-reranker-v2-m3",
        }])


if __name__ == "__main__":
    unittest.main()
