import asyncio
import unittest
from typing import Any

import importlib

eval_context_rag = importlib.import_module("eval.eval_context_rag")


class MultiQueryRecallPatchTests(unittest.TestCase):
    def test_build_query_variants_for_multi_doc_query(self):
        variants = eval_context_rag.build_query_variants(
            "新质生产力对制造业、产业链、科技创新分别有什么影响？",
            case_type="E_multi_document",
        )

        self.assertGreaterEqual(len(variants), 1)
        self.assertLessEqual(len(variants), 2)
        self.assertIn("新质生产力对制造业、产业链、科技创新分别有什么影响？", variants)

    def test_build_query_variants_for_context_follow_up(self):
        variants = eval_context_rag.build_query_variants(
            "新质生产力 高质量发展 先进制造 对先进制造有什么影响？",
            case_type="B_context_follow_up",
        )

        self.assertGreaterEqual(len(variants), 1)
        self.assertLessEqual(len(variants), 2)

    def test_build_query_variants_skips_non_eligible_case_type(self):
        variants = eval_context_rag.build_query_variants(
            "新质生产力有什么新闻？",
            case_type="A_exact_news_qa",
        )

        self.assertEqual(variants, ["新质生产力有什么新闻？"])

    def test_merge_and_dedupe_candidates_preserves_best_score(self):
        candidates = [
            {"id": "a", "title": "t1", "score": 0.9, "evidence_id": "news:a"},
            {"id": "b", "title": "t2", "score": 0.8, "evidence_id": "news:b"},
            {"id": "a", "title": "t1", "score": 0.95, "evidence_id": "news:a"},
        ]

        merged = eval_context_rag.merge_dedupe_candidates(candidates)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["id"], "a")
        self.assertAlmostEqual(merged[0]["score"], 0.95)

    def test_multi_query_eligible_case_types(self):
        self.assertTrue(eval_context_rag.is_multi_query_eligible("B_context_follow_up"))
        self.assertTrue(eval_context_rag.is_multi_query_eligible("E_multi_document"))
        self.assertTrue(eval_context_rag.is_multi_query_eligible("C_time_sensitive"))
        self.assertFalse(eval_context_rag.is_multi_query_eligible("A_exact_news_qa"))
        self.assertFalse(eval_context_rag.is_multi_query_eligible("G_no_answer"))


if __name__ == "__main__":
    unittest.main()
