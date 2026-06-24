import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelCoverageTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_summarizes_projected_coverage_from_accept_rows(self):
        try:
            from scripts.report_reviewed_label_coverage import summarize_reviewed_label_coverage
        except ModuleNotFoundError:
            self.fail("scripts.report_reviewed_label_coverage should exist")

        gold_rows = [
            {"id": "a1", "case_type": "A_exact_news_qa"},
            {"id": "b1", "case_type": "B_context_follow_up"},
        ]
        label_rows = [
            {
                "candidate_id": "candidate_a2",
                "decision": "accept_as_gold",
                "gold_id": "a2",
                "question": "A2?",
                "turns": None,
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:abcd1234"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "A_exact_news_qa",
                "notes": "Reviewed.",
            },
            {
                "candidate_id": "candidate_b1",
                "decision": "merge_with_existing",
                "existing_gold_id": "b1",
                "case_type": "B_context_follow_up",
                "notes": "Duplicate.",
            },
        ]
        targets = {"A_exact_news_qa": 2, "B_context_follow_up": 2}

        summary = summarize_reviewed_label_coverage(gold_rows, label_rows, targets=targets)

        self.assertEqual(summary.formal_count, 2)
        self.assertEqual(summary.label_count, 2)
        self.assertEqual(summary.accepted_count, 1)
        self.assertEqual(summary.merge_count, 1)
        self.assertEqual(summary.projected_formal_count, 3)
        self.assertEqual(summary.projected_counts_after_accepts["A_exact_news_qa"], 2)
        self.assertEqual(summary.deficits_after_accepts["A_exact_news_qa"], 0)
        self.assertEqual(summary.deficits_after_accepts["B_context_follow_up"], 1)
        self.assertIn("B_context_follow_up remains below target by 1", summary.blockers)

    def test_empty_reviewed_labels_report_missing_accepts(self):
        try:
            from scripts.report_reviewed_label_coverage import summarize_reviewed_label_coverage
        except ModuleNotFoundError:
            self.fail("scripts.report_reviewed_label_coverage should exist")

        summary = summarize_reviewed_label_coverage(
            [{"id": "a1", "case_type": "A_exact_news_qa"}],
            [],
            targets={"A_exact_news_qa": 2},
            target_total=2,
        )

        self.assertEqual(summary.label_count, 0)
        self.assertEqual(summary.accepted_count, 0)
        self.assertEqual(summary.projected_formal_count, 1)
        self.assertIn("no accepted reviewed labels", summary.blockers)
        self.assertIn("projected formal count 1 is below 2", summary.blockers)

    def test_write_report_outputs_json_and_markdown(self):
        try:
            from scripts.report_reviewed_label_coverage import write_reviewed_label_coverage_report
        except ModuleNotFoundError:
            self.fail("scripts.report_reviewed_label_coverage should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            labels = root / "labels.jsonl"
            report = root / "report.md"
            json_report = root / "report.json"
            self._write_jsonl(gold, [{"id": "a1", "case_type": "A_exact_news_qa"}])
            self._write_jsonl(
                labels,
                [
                    {
                        "candidate_id": "candidate_a2",
                        "decision": "accept_as_gold",
                        "gold_id": "a2",
                        "question": "A2?",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": ["news:jjrb:abcd1234"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "A_exact_news_qa",
                        "notes": "Reviewed.",
                    }
                ],
            )

            summary = write_reviewed_label_coverage_report(
                gold,
                labels,
                report,
                json_report,
                targets={"A_exact_news_qa": 2},
                target_total=2,
            )

            self.assertEqual(summary.projected_formal_count, 2)
            self.assertTrue(report.exists())
            self.assertTrue(json_report.exists())
            data = json.loads(json_report.read_text(encoding="utf-8"))
            self.assertEqual(data["accepted_count"], 1)
