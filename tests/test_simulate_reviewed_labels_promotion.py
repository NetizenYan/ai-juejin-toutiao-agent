import json
import tempfile
import unittest
from pathlib import Path


class SimulateReviewedLabelsPromotionTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def _candidate(self) -> dict:
        return {"id": "candidate_a1", "case_type": "A_exact_news_qa"}

    def _label(self) -> dict:
        return {
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

    def test_simulation_applies_preview_to_sandbox_without_modifying_real_official(self):
        try:
            from scripts.simulate_reviewed_labels_promotion import simulate_reviewed_labels_promotion
        except ModuleNotFoundError:
            self.fail("scripts.simulate_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            sandbox = root / "sandbox"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [self._candidate()])
            self._write_jsonl(preview, [self._label()])
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")

            result = simulate_reviewed_labels_promotion(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                targets={"A_exact_news_qa": 1},
                target_total=1,
            )

            after = official.read_text(encoding="utf-8")

        self.assertTrue(result["simulation_applied"])
        self.assertTrue(result["real_official_unchanged"])
        self.assertEqual(before, after)
        self.assertEqual(result["sandbox_official"]["row_count"], 1)
        self.assertEqual(
            result["pipeline_state"]["reviewed_label_stage"],
            "reviewed_labels_ready_for_gold_expansion",
        )
        self.assertTrue(result["pipeline_state"]["reviewed_labels_ready_for_gold_expansion"])

    def test_simulation_blocks_invalid_preview_and_keeps_real_official_unchanged(self):
        try:
            from scripts.simulate_reviewed_labels_promotion import simulate_reviewed_labels_promotion
        except ModuleNotFoundError:
            self.fail("scripts.simulate_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            sandbox = root / "sandbox"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [])
            self._write_jsonl(preview, [self._label()])
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")

            result = simulate_reviewed_labels_promotion(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                targets={"A_exact_news_qa": 1},
                target_total=1,
            )

            after = official.read_text(encoding="utf-8")

        self.assertFalse(result["simulation_applied"])
        self.assertTrue(result["real_official_unchanged"])
        self.assertEqual(before, after)
        self.assertIn("preview validation: line 1: unknown candidate_id candidate_a1", result["blockers"])

    def test_write_simulation_report_outputs_artifacts(self):
        try:
            from scripts.simulate_reviewed_labels_promotion import write_simulation_report
        except ModuleNotFoundError:
            self.fail("scripts.simulate_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            sandbox = root / "sandbox"
            report = root / "simulation.md"
            json_report = root / "simulation.json"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [self._candidate()])
            self._write_jsonl(preview, [self._label()])
            self._write_jsonl(official, [])

            result = write_simulation_report(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                report,
                json_report,
                targets={"A_exact_news_qa": 1},
                target_total=1,
            )
            report_text = report.read_text(encoding="utf-8")
            json_report_exists = json_report.exists()

        self.assertTrue(result["simulation_applied"])
        self.assertIn("Sandbox only", report_text)
        self.assertTrue(json_report_exists)
