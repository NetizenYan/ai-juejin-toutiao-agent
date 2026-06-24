import json
import tempfile
import unittest
from pathlib import Path


class OfficialLabelsPreviewTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_preview_copies_draft_rows_without_modifying_decisions(self):
        try:
            from scripts.build_reviewed_labels_official_preview import build_preview_rows
        except ModuleNotFoundError:
            self.fail("scripts.build_reviewed_labels_official_preview should exist")

        rows, summary = build_preview_rows(
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
                },
                {
                    "candidate_id": "candidate_b1",
                    "decision": "merge_with_existing",
                    "existing_gold_id": "b1",
                    "case_type": "B_context_follow_up",
                    "notes": "Duplicate.",
                },
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["decision"], "accept_as_gold")
        self.assertEqual(rows[1]["decision"], "merge_with_existing")
        self.assertTrue(summary["preview_only"])
        self.assertEqual(summary["decision_counts"]["accept_as_gold"], 1)
        self.assertEqual(summary["decision_counts"]["merge_with_existing"], 1)

    def test_write_preview_outputs_jsonl_summary_and_report(self):
        try:
            from scripts.build_reviewed_labels_official_preview import write_official_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_reviewed_labels_official_preview should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            draft = root / "draft.jsonl"
            output = root / "reviewed_labels_preview.jsonl"
            summary_path = root / "summary.json"
            report = root / "report.md"
            self._write_jsonl(
                draft,
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

            summary = write_official_preview(draft, output, summary_path, report)

            self.assertTrue(summary["preview_only"])
            self.assertEqual(summary["row_count"], 1)
            self.assertTrue(output.exists())
            self.assertTrue(summary_path.exists())
            self.assertTrue(report.exists())
            preview_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(preview_rows[0]["candidate_id"], "candidate_a1")
            self.assertIn("Preview Only", report.read_text(encoding="utf-8"))
