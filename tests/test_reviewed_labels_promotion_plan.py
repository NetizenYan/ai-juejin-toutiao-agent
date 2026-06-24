import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelsPromotionPlanTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_plan_reports_manual_transaction_ready_for_empty_official_and_nonempty_preview(self):
        try:
            from scripts.plan_reviewed_labels_promotion import plan_promotion_transaction
        except ModuleNotFoundError:
            self.fail("scripts.plan_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            preview = root / "preview.jsonl"
            self._write_jsonl(official, [])
            self._write_jsonl(
                preview,
                [
                    {
                        "candidate_id": "candidate_a1",
                        "decision": "accept_as_gold",
                        "gold_id": "a1_reviewed",
                        "question": "最近新质生产力有什么新闻？",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": ["news:jjrb:a1"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "A_exact_news_qa",
                        "notes": "Reviewed draft.",
                    }
                ],
            )

            plan = plan_promotion_transaction(preview, official)

        self.assertTrue(plan["dry_run_only"])
        self.assertTrue(plan["manual_transaction_ready"])
        self.assertEqual(plan["preview"]["row_count"], 1)
        self.assertEqual(plan["official"]["row_count"], 0)
        self.assertEqual(plan["blockers"], [])
        self.assertIn("manual confirmation required", plan["actions"][0])

    def test_plan_blocks_empty_preview(self):
        try:
            from scripts.plan_reviewed_labels_promotion import plan_promotion_transaction
        except ModuleNotFoundError:
            self.fail("scripts.plan_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            preview = root / "preview.jsonl"
            self._write_jsonl(official, [])
            self._write_jsonl(preview, [])

            plan = plan_promotion_transaction(preview, official)

        self.assertFalse(plan["manual_transaction_ready"])
        self.assertIn("preview reviewed-label file has no rows", plan["blockers"])

    def test_write_plan_outputs_report_and_does_not_modify_official(self):
        try:
            from scripts.plan_reviewed_labels_promotion import write_promotion_plan
        except ModuleNotFoundError:
            self.fail("scripts.plan_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            preview = root / "preview.jsonl"
            report = root / "promotion_plan.md"
            json_report = root / "promotion_plan.json"
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")
            self._write_jsonl(
                preview,
                [
                    {
                        "candidate_id": "candidate_a1",
                        "decision": "merge_with_existing",
                        "existing_gold_id": "a1",
                        "case_type": "A_exact_news_qa",
                        "notes": "Duplicate.",
                    }
                ],
            )

            plan = write_promotion_plan(preview, official, report, json_report)
            after = official.read_text(encoding="utf-8")
            report_exists = report.exists()
            json_report_exists = json_report.exists()
            report_text = report.read_text(encoding="utf-8")

        self.assertTrue(plan["manual_transaction_ready"])
        self.assertEqual(before, after)
        self.assertTrue(report_exists)
        self.assertTrue(json_report_exists)
        self.assertIn("Dry-run only", report_text)
