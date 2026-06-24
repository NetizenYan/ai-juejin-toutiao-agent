import json
import tempfile
import unittest
from pathlib import Path


class GoldTuningGateTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, count: int) -> None:
        path.write_text(
            "\n".join(json.dumps({"id": f"case_{idx}"}) for idx in range(count)) + "\n",
            encoding="utf-8",
        )

    def test_gate_stays_closed_when_coverage_and_splits_are_missing(self):
        try:
            from scripts.check_gold_tuning_gate import check_tuning_gate
        except ModuleNotFoundError:
            self.fail("scripts.check_gold_tuning_gate should exist")

        coverage = {
            "formal_count": 50,
            "formal_counts": {
                "A_exact_news_qa": 6,
                "B_context_follow_up": 6,
                "C_time_sensitive": 6,
                "D_source_limited": 7,
                "E_multi_document": 7,
                "F_similar_distractor": 6,
                "G_no_answer": 6,
                "H_investment_boundary": 6,
            },
        }

        result = check_tuning_gate(coverage)

        self.assertFalse(result.ok)
        messages = "\n".join(result.blockers)
        self.assertIn("formal gold count 50 is below 100", messages)
        self.assertIn("held-out split is missing", messages)
        self.assertIn("train baseline report is missing", messages)
        self.assertIn("A_exact_news_qa has 6 formal cases, below 10", messages)

    def test_gate_opens_when_minimums_splits_and_reports_exist(self):
        try:
            from scripts.check_gold_tuning_gate import check_tuning_gate
        except ModuleNotFoundError:
            self.fail("scripts.check_gold_tuning_gate should exist")

        coverage = {
            "formal_count": 104,
            "formal_counts": {
                "A_exact_news_qa": 14,
                "B_context_follow_up": 14,
                "C_time_sensitive": 12,
                "D_source_limited": 12,
                "E_multi_document": 12,
                "F_similar_distractor": 10,
                "G_no_answer": 10,
                "H_investment_boundary": 10,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train_path = root / "train.jsonl"
            heldout_path = root / "heldout.jsonl"
            train_report = root / "train_report.json"
            heldout_report = root / "heldout_report.json"
            self._write_jsonl(train_path, 74)
            self._write_jsonl(heldout_path, 30)
            train_report.write_text("{}", encoding="utf-8")
            heldout_report.write_text("{}", encoding="utf-8")

            result = check_tuning_gate(
                coverage,
                train_split_path=train_path,
                heldout_split_path=heldout_path,
                train_report_path=train_report,
                heldout_report_path=heldout_report,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.blockers, [])
        self.assertEqual(result.formal_count, 104)
        self.assertEqual(result.heldout_count, 30)
