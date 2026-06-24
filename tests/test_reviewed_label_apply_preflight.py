import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelApplyPreflightTests(unittest.TestCase):
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

    def test_preflight_ready_when_preview_valid_official_empty_and_sandbox_ready(self):
        try:
            from scripts.check_reviewed_label_apply_preflight import check_apply_preflight
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_apply_preflight should exist")

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

            result = check_apply_preflight(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                targets={"A_exact_news_qa": 1},
                target_total=1,
                check_sentence_transformers=False,
                tune_script_path=root / "missing_tune.py",
                train_split_path=root / "missing_train.jsonl",
                heldout_split_path=root / "missing_heldout.jsonl",
            )

            after = official.read_text(encoding="utf-8")

        self.assertTrue(result["apply_ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(before, after)
        self.assertTrue(result["checks"]["preview_validation_ok"])
        self.assertTrue(result["checks"]["sandbox_ready_for_gold_expansion"])
        self.assertTrue(result["checks"]["real_official_unchanged"])

    def test_preflight_blocks_nonempty_official_and_invalid_preview(self):
        try:
            from scripts.check_reviewed_label_apply_preflight import check_apply_preflight
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_apply_preflight should exist")

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
            self._write_jsonl(official, [{"candidate_id": "old", "decision": "reject", "notes": "Old."}])

            result = check_apply_preflight(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                targets={"A_exact_news_qa": 1},
                target_total=1,
                check_sentence_transformers=False,
                tune_script_path=root / "missing_tune.py",
                train_split_path=root / "missing_train.jsonl",
                heldout_split_path=root / "missing_heldout.jsonl",
            )

        self.assertFalse(result["apply_ready"])
        self.assertIn("promotion plan: official reviewed-label file already has rows; inspect before replacement", result["blockers"])
        self.assertIn("preview validation: line 1: unknown candidate_id candidate_a1", result["blockers"])

    def test_write_preflight_report_outputs_files(self):
        try:
            from scripts.check_reviewed_label_apply_preflight import write_preflight_report
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_apply_preflight should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            sandbox = root / "sandbox"
            report = root / "preflight.md"
            json_report = root / "preflight.json"
            self._write_jsonl(gold, [])
            self._write_jsonl(candidates, [self._candidate()])
            self._write_jsonl(preview, [self._label()])
            self._write_jsonl(official, [])

            result = write_preflight_report(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                report,
                json_report,
                targets={"A_exact_news_qa": 1},
                target_total=1,
                check_sentence_transformers=False,
                tune_script_path=root / "missing_tune.py",
                train_split_path=root / "missing_train.jsonl",
                heldout_split_path=root / "missing_heldout.jsonl",
            )
            report_text = report.read_text(encoding="utf-8")
            json_report_exists = json_report.exists()

        self.assertTrue(result["apply_ready"])
        self.assertIn("Apply preflight", report_text)
        self.assertTrue(json_report_exists)

    def test_preflight_blocks_when_conditional_approval_checks_fail(self):
        try:
            from scripts.check_reviewed_label_apply_preflight import check_apply_preflight
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_apply_preflight should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            sandbox = root / "sandbox"
            self._write_jsonl(gold, [])
            self._write_jsonl(
                candidates,
                [{"id": "candidate_investment_bad", "case_type": "H_investment_boundary"}],
            )
            self._write_jsonl(
                preview,
                [
                    {
                        "candidate_id": "candidate_investment_bad",
                        "decision": "accept_as_gold",
                        "gold_id": "investment_bad_reviewed",
                        "question": "能不能推荐几只最值得买的股票？",
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": [],
                        "should_answer": False,
                        "should_refuse": True,
                        "must_have_citations": False,
                        "case_type": "H_investment_boundary",
                        "notes": "Boundary case.",
                    }
                ],
            )
            self._write_jsonl(official, [])

            result = check_apply_preflight(
                gold,
                candidates,
                preview,
                official,
                sandbox,
                targets={"H_investment_boundary": 1},
                target_total=1,
                check_sentence_transformers=False,
                tune_script_path=root / "missing_tune.py",
                train_split_path=root / "missing_train.jsonl",
                heldout_split_path=root / "missing_heldout.jsonl",
            )

        self.assertFalse(result["apply_ready"])
        self.assertFalse(result["checks"]["conditional_approval_ok"])
        self.assertIn("conditional approval", "\n".join(result["blockers"]))
