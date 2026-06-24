import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelPipelineStateTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_empty_official_labels_keep_pipeline_waiting_for_manual_confirmation(self):
        try:
            from scripts.check_reviewed_label_pipeline_state import assess_pipeline_state
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_pipeline_state should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            official = root / "official.jsonl"
            preview = root / "preview.jsonl"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [])
            self._write_jsonl(official, [])
            self._write_jsonl(preview, [{"candidate_id": "candidate_a1", "decision": "accept_as_gold"}])

            state = assess_pipeline_state(
                gold,
                candidates,
                official,
                preview_labels_path=preview,
                targets={},
                target_total=1,
            )

        self.assertEqual(state["reviewed_label_stage"], "pending_manual_confirmation")
        self.assertFalse(state["reviewed_labels_ready_for_gold_expansion"])
        self.assertIn("official reviewed-label file has no rows", state["blockers"])
        self.assertFalse(state["automatic_tuning_gate"]["ok"])

    def test_confirmed_official_labels_can_be_ready_for_gold_expansion_while_tuning_gate_stays_closed(self):
        try:
            from scripts.check_reviewed_label_pipeline_state import assess_pipeline_state
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_pipeline_state should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            official = root / "official.jsonl"
            candidate = {"id": "candidate_a1", "case_type": "A_exact_news_qa"}
            label = {
                "candidate_id": "candidate_a1",
                "decision": "accept_as_gold",
                "gold_id": "a1_reviewed",
                "question": "经济日报，新质生产力有什么新闻？",
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:a1"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "A_exact_news_qa",
                "notes": "Confirmed.",
            }
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [candidate])
            self._write_jsonl(official, [label])

            state = assess_pipeline_state(
                gold,
                candidates,
                official,
                targets={"A_exact_news_qa": 1},
                target_total=1,
            )

        self.assertEqual(state["reviewed_label_stage"], "reviewed_labels_ready_for_gold_expansion")
        self.assertTrue(state["reviewed_labels_ready_for_gold_expansion"])
        self.assertEqual(state["blockers"], [])
        self.assertFalse(state["automatic_tuning_gate"]["ok"])
        self.assertIn("formal gold count 0 is below 100", state["automatic_tuning_gate"]["blockers"])

    def test_write_pipeline_state_report_does_not_modify_official_labels(self):
        try:
            from scripts.check_reviewed_label_pipeline_state import write_pipeline_state_report
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_pipeline_state should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            official = root / "official.jsonl"
            report = root / "state.md"
            json_report = root / "state.json"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [])
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")

            state = write_pipeline_state_report(
                gold,
                candidates,
                official,
                report,
                json_report,
                targets={},
                target_total=1,
            )
            after = official.read_text(encoding="utf-8")
            report_text = report.read_text(encoding="utf-8")
            json_report_exists = json_report.exists()

        self.assertEqual(before, after)
        self.assertFalse(state["reviewed_labels_ready_for_gold_expansion"])
        self.assertIn("Manual confirmation is still required", report_text)
        self.assertTrue(json_report_exists)
