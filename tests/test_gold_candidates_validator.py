import json
import tempfile
import unittest
from pathlib import Path


class GoldCandidatesValidatorTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_valid_candidate_queue_passes(self):
        try:
            from scripts.validate_gold_candidates import validate_candidates
        except ModuleNotFoundError:
            self.fail("scripts.validate_gold_candidates should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "candidates.jsonl"
            self._write_jsonl(
                path,
                [
                    {
                        "id": "candidate_source_005",
                        "source": "3.2E_failed_case",
                        "case_type": "D_source_limited",
                        "query_or_turns": ["经济日报，新质生产力如何影响制造业？"],
                        "reason": "source-constrained near-miss",
                        "status": "needs_label_review",
                    }
                ],
            )

            result = validate_candidates(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.errors, [])

    def test_invalid_candidate_queue_reports_actionable_errors(self):
        try:
            from scripts.validate_gold_candidates import validate_candidates
        except ModuleNotFoundError:
            self.fail("scripts.validate_gold_candidates should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "candidates.jsonl"
            self._write_jsonl(
                path,
                [
                    {
                        "id": "candidate_dup",
                        "source": "3.2E_failed_case",
                        "case_type": "D_source_limited",
                        "query_or_turns": ["经济日报，新质生产力如何影响制造业？"],
                        "reason": "near-miss",
                        "status": "needs_label_review",
                    },
                    {
                        "id": "candidate_dup",
                        "source": "3.2E_failed_case",
                        "case_type": "bad_type",
                        "query_or_turns": [],
                        "reason": "",
                        "status": "accepted",
                    },
                ],
            )

            result = validate_candidates(path)

        self.assertFalse(result.ok)
        self.assertEqual(result.row_count, 2)
        messages = "\n".join(result.errors)
        self.assertIn("line 2: duplicate id candidate_dup", messages)
        self.assertIn("line 2: invalid case_type 'bad_type'", messages)
        self.assertIn("line 2: query_or_turns must be a non-empty list of non-empty strings", messages)
        self.assertIn("line 2: reason is required", messages)
        self.assertIn("line 2: invalid status 'accepted'", messages)
