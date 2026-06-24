import unittest

from evals import retrieval_eval


class RetrievalEvalMetricTests(unittest.TestCase):
    def test_retrieval_metrics_measure_hit_mrr_and_recall(self):
        metrics = retrieval_eval.retrieval_metrics([9, 7, 8], {7, 8}, k=5)

        self.assertEqual(metrics["hit"], 1)
        self.assertAlmostEqual(metrics["mrr"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 1.0)

    def test_evidence_recall_counts_keyword_hits_in_topk_chunks(self):
        items = [
            {"summary": "无关内容"},
            {"summary": "这段包含人工智能政策细节"},
        ]

        metrics = retrieval_eval.evidence_recall_metrics(items, ["人工智能"], k=5)

        self.assertEqual(metrics["evidence_hit"], 1)

    def test_body_evidence_metrics_count_topk_parents_with_body_chunks(self):
        body_evidence = [
            {"parent_news_id": 7, "evidence_id": "news:7#body:0"},
            {"id": 9, "evidence_id": "news:9#body:0"},
        ]

        metrics = retrieval_eval.body_evidence_metrics([7, 8, 9], body_evidence, k=2)

        self.assertEqual(metrics["body_evidence_count"], 1)
        self.assertAlmostEqual(metrics["body_evidence_coverage"], 0.5)

    def test_default_query_router_comparison_strategies(self):
        args = retrieval_eval.parse_args([])
        strategies = retrieval_eval.parse_strategies(args.strategies)

        self.assertEqual(
            [strategy.name for strategy in strategies],
            ["summary-only", "global body_fallback_slots=1", "query_router_v1"],
        )

    def test_strategy_table_has_required_columns(self):
        table = retrieval_eval.format_strategy_table([
            {
                "strategy": "summary-only",
                "hit_at_k": 1.0,
                "mrr": 0.5,
                "recall_at_k": 0.75,
                "evidence_recall_at_k": 0.25,
                "body_evidence_at_k": 0.0,
                "latency_ms": 12.4,
                "notes": "baseline",
            }
        ])

        self.assertIn("| Strategy | Hit@5 | MRR | Recall@5 | EvidenceRecall@5 | BodyEvidence@5 | Latency | Notes |", table)
        self.assertIn("| summary-only | 100% | 0.500 | 75% | 25% | 0% | 12ms | baseline |", table)


if __name__ == "__main__":
    unittest.main()
