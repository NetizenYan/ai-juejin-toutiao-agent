import json
import tempfile
import unittest
from pathlib import Path


class BuildExpandedGoldPreviewTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_accept_rows_are_appended_and_merge_rows_are_skipped(self):
        try:
            from scripts.build_expanded_gold_preview import build_expanded_gold_rows
        except ModuleNotFoundError:
            self.fail("scripts.build_expanded_gold_preview should exist")

        gold_rows = [
            {
                "id": "exact_001",
                "question": "Existing?",
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:aaaa1111"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "A_exact_news_qa",
                "notes": "Existing.",
            }
        ]
        label_rows = [
            {
                "candidate_id": "candidate_exact_002",
                "decision": "accept_as_gold",
                "gold_id": "exact_002",
                "question": "New?",
                "turns": None,
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:bbbb2222"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "A_exact_news_qa",
                "notes": "Reviewed.",
            },
            {
                "candidate_id": "candidate_exact_001",
                "decision": "merge_with_existing",
                "existing_gold_id": "exact_001",
                "case_type": "A_exact_news_qa",
                "notes": "Duplicate.",
            },
        ]

        expanded, summary = build_expanded_gold_rows(gold_rows, label_rows)

        self.assertEqual(len(expanded), 2)
        self.assertEqual(summary["base_count"], 1)
        self.assertEqual(summary["accepted_added"], 1)
        self.assertEqual(summary["merge_skipped"], 1)
        self.assertEqual(expanded[-1]["id"], "exact_002")
        self.assertEqual(expanded[-1]["question"], "New?")
        self.assertNotIn("turns", expanded[-1])

    def test_turns_are_preserved_for_multi_turn_accept_rows(self):
        try:
            from scripts.build_expanded_gold_preview import build_expanded_gold_rows
        except ModuleNotFoundError:
            self.fail("scripts.build_expanded_gold_preview should exist")

        expanded, _ = build_expanded_gold_rows(
            [],
            [
                {
                    "candidate_id": "candidate_context_001",
                    "decision": "accept_as_gold",
                    "gold_id": "context_001",
                    "question": None,
                    "turns": ["First", "Follow-up"],
                    "expected_route": "econ_finance_query",
                    "gold_evidence_ids": ["news:jjrb:bbbb2222"],
                    "should_answer": True,
                    "should_refuse": False,
                    "must_have_citations": True,
                    "case_type": "B_context_follow_up",
                    "notes": "Reviewed.",
                }
            ],
        )

        self.assertEqual(expanded[0]["id"], "context_001")
        self.assertEqual(expanded[0]["turns"], ["First", "Follow-up"])
        self.assertNotIn("question", expanded[0])

    def test_conditional_approval_fields_are_preserved(self):
        try:
            from scripts.build_expanded_gold_preview import build_expanded_gold_rows
        except ModuleNotFoundError:
            self.fail("scripts.build_expanded_gold_preview should exist")

        expanded, _ = build_expanded_gold_rows(
            [],
            [
                {
                    "candidate_id": "candidate_investment_001",
                    "decision": "accept_as_gold",
                    "gold_id": "investment_001",
                    "question": "Can I buy this stock?",
                    "turns": None,
                    "expected_route": "econ_finance_query",
                    "gold_evidence_ids": [],
                    "should_answer": False,
                    "should_refuse": True,
                    "must_have_citations": False,
                    "case_type": "H_investment_boundary",
                    "allowed_fact_summary": True,
                    "should_refuse_investment_advice": True,
                    "forbidden": ["推荐具体股票", "推荐买入卖出", "保证收益", "短线操作建议", "加仓建议"],
                    "notes": "Reviewed.",
                }
            ],
        )

        self.assertTrue(expanded[0]["allowed_fact_summary"])
        self.assertTrue(expanded[0]["should_refuse_investment_advice"])
        self.assertIn("推荐具体股票", expanded[0]["forbidden"])

    def test_duplicate_gold_id_raises_value_error(self):
        try:
            from scripts.build_expanded_gold_preview import build_expanded_gold_rows
        except ModuleNotFoundError:
            self.fail("scripts.build_expanded_gold_preview should exist")

        with self.assertRaisesRegex(ValueError, "duplicate gold id exact_001"):
            build_expanded_gold_rows(
                [{"id": "exact_001", "case_type": "A_exact_news_qa"}],
                [
                    {
                        "candidate_id": "candidate_exact_001",
                        "decision": "accept_as_gold",
                        "gold_id": "exact_001",
                        "question": "Duplicate?",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": ["news:jjrb:bbbb2222"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "A_exact_news_qa",
                        "notes": "Reviewed.",
                    }
                ],
            )

    def test_write_expanded_gold_preview_outputs_jsonl_and_summary(self):
        try:
            from scripts.build_expanded_gold_preview import write_expanded_gold_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_expanded_gold_preview should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            labels = root / "labels.jsonl"
            output = root / "expanded.jsonl"
            summary_path = root / "summary.json"
            self._write_jsonl(gold, [{"id": "a1", "question": "A", "case_type": "A_exact_news_qa"}])
            self._write_jsonl(
                labels,
                [
                    {
                        "candidate_id": "candidate_a2",
                        "decision": "accept_as_gold",
                        "gold_id": "a2",
                        "question": "A2",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": ["news:jjrb:bbbb2222"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "A_exact_news_qa",
                        "notes": "Reviewed.",
                    }
                ],
            )

            summary = write_expanded_gold_preview(gold, labels, output, summary_path)

            self.assertEqual(summary["projected_count"], 2)
            self.assertTrue(output.exists())
            self.assertTrue(summary_path.exists())
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["id"] for row in rows], ["a1", "a2"])
