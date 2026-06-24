import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch


reranker = __import__("harness.reranker", fromlist=["reranker"])


class FusionRerankTests(unittest.TestCase):
    def _items(self):
        return [
            {"id": "a", "title": "在发展新质生产力上走在前列", "summary": "制造业", "score": 0.90, "source": "jjrb"},
            {"id": "b", "title": "高质量发展硬道理", "summary": "GDP", "score": 0.80, "source": "rmrb"},
            {"id": "c", "title": "无关体育报道", "summary": "足球", "score": 0.70, "source": "old"},
        ]

    def test_fusion_rerank_combines_vector_and_cross_encoder_scores(self):
        def fake_predict(pairs):
            return [0.9, 0.1, 0.05]

        with patch.object(reranker, "_load") as mock_load:
            mock_load.return_value = SimpleNamespace(predict=fake_predict)
            ranked = asyncio.run(reranker.fusion_rerank(
                "新质生产力 制造业",
                self._items(),
                top_k=3,
                cross_encoder_weight=0.5,
                vector_weight=0.3,
                light_bonus_weight=0.2,
            ))

        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0]["id"], "a")
        self.assertIn("fusion_score", ranked[0])
        self.assertIn("score_breakdown", ranked[0])
        breakdown = ranked[0]["score_breakdown"]
        self.assertIn("vector_score_norm", breakdown)
        self.assertIn("cross_encoder_score_norm", breakdown)
        self.assertIn("light_rule_bonus", breakdown)

    def test_fusion_rerank_does_not_let_cross_encoder_completely_override_vector(self):
        def fake_predict(pairs):
            return [0.05, 0.1, 0.9]

        with patch.object(reranker, "_load") as mock_load:
            mock_load.return_value = SimpleNamespace(predict=fake_predict)
            ranked = asyncio.run(reranker.fusion_rerank(
                "新质生产力 制造业",
                self._items(),
                top_k=3,
                cross_encoder_weight=0.4,
                vector_weight=0.4,
                light_bonus_weight=0.2,
            ))

        ids = [item["id"] for item in ranked]
        self.assertIn("a", ids[:2])

    def test_fusion_rerank_emits_score_breakdown(self):
        def fake_predict(pairs):
            return [0.9, 0.5, 0.1]

        with patch.object(reranker, "_load") as mock_load:
            mock_load.return_value = SimpleNamespace(predict=fake_predict)
            ranked = asyncio.run(reranker.fusion_rerank(
                "新质生产力",
                self._items(),
                top_k=3,
            ))

        for item in ranked:
            self.assertIn("score_breakdown", item)
            breakdown = item["score_breakdown"]
            self.assertIn("vector_score_norm", breakdown)
            self.assertIn("cross_encoder_score_norm", breakdown)
            self.assertIn("light_rule_bonus", breakdown)
            self.assertIn("fusion_score", breakdown)

    def test_fusion_rerank_falls_back_when_cross_encoder_fails(self):
        def fake_predict(pairs):
            raise RuntimeError("model offline")

        with patch.object(reranker, "_load") as mock_load:
            mock_load.return_value = SimpleNamespace(predict=fake_predict)
            ranked = asyncio.run(reranker.fusion_rerank(
                "新质生产力",
                self._items(),
                top_k=3,
            ))

        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
