import json
import tempfile
import unittest
from pathlib import Path


class GoldReviewedLabelsTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_accept_as_gold_requires_evidence_and_candidate_membership(self):
        try:
            from scripts.validate_gold_reviewed_labels import validate_reviewed_labels
        except ModuleNotFoundError:
            self.fail("scripts.validate_gold_reviewed_labels should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates_path = root / "candidates.jsonl"
            labels_path = root / "labels.jsonl"
            self._write_jsonl(
                candidates_path,
                [
                    {
                        "id": "candidate_source_005",
                        "source": "3.2E_failed_case",
                        "case_type": "D_source_limited",
                        "query_or_turns": ["经济日报，新质生产力如何影响制造业？"],
                        "reason": "near miss",
                        "status": "needs_label_review",
                    }
                ],
            )
            self._write_jsonl(
                labels_path,
                [
                    {
                        "candidate_id": "candidate_source_005",
                        "decision": "accept_as_gold",
                        "gold_id": "source_005_reviewed",
                        "question": "经济日报，新质生产力如何影响制造业？",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": [],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "D_source_limited",
                        "notes": "Reviewed manually.",
                    },
                    {
                        "candidate_id": "candidate_missing",
                        "decision": "reject",
                        "notes": "Unknown candidate should be reported.",
                    },
                ],
            )

            result = validate_reviewed_labels(candidates_path, labels_path)

        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.ok)
        messages = "\n".join(result.errors)
        self.assertIn("line 1: answerable accept_as_gold requires non-empty gold_evidence_ids", messages)
        self.assertIn("line 2: unknown candidate_id candidate_missing", messages)

    def test_valid_reviewed_labels_pass(self):
        try:
            from scripts.validate_gold_reviewed_labels import validate_reviewed_labels
        except ModuleNotFoundError:
            self.fail("scripts.validate_gold_reviewed_labels should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates_path = root / "candidates.jsonl"
            labels_path = root / "labels.jsonl"
            self._write_jsonl(
                candidates_path,
                [
                    {
                        "id": "candidate_source_005",
                        "source": "3.2E_failed_case",
                        "case_type": "D_source_limited",
                        "query_or_turns": ["经济日报，新质生产力如何影响制造业？"],
                        "reason": "near miss",
                        "status": "needs_label_review",
                    },
                    {
                        "id": "candidate_no_answer_006",
                        "source": "3.2E_failed_case",
                        "case_type": "G_no_answer",
                        "query_or_turns": ["站内有没有关于星河制造业跃迁法案2040的消息？"],
                        "reason": "fictional no-answer",
                        "status": "needs_label_review",
                    },
                ],
            )
            self._write_jsonl(
                labels_path,
                [
                    {
                        "candidate_id": "candidate_source_005",
                        "decision": "accept_as_gold",
                        "gold_id": "source_005_reviewed",
                        "question": "经济日报，新质生产力如何影响制造业？",
                        "turns": None,
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": ["news:jjrb:a9d8dd5ff9ec1f03"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": "D_source_limited",
                        "notes": "Reviewed manually.",
                    },
                    {
                        "candidate_id": "candidate_no_answer_006",
                        "decision": "reject",
                        "notes": "Already covered by existing no-answer gold case.",
                    },
                ],
            )

            result = validate_reviewed_labels(candidates_path, labels_path)

        self.assertTrue(result.ok)
        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.errors, [])

    def test_accept_no_answer_gold_allows_empty_evidence_ids(self):
        try:
            from scripts.validate_gold_reviewed_labels import validate_reviewed_labels
        except ModuleNotFoundError:
            self.fail("scripts.validate_gold_reviewed_labels should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates_path = root / "candidates.jsonl"
            labels_path = root / "labels.jsonl"
            self._write_jsonl(
                candidates_path,
                [
                    {
                        "id": "candidate_no_answer_007",
                        "source": "3.3_intake_plan_20260622",
                        "case_type": "G_no_answer",
                        "query_or_turns": ["Any news about fictional policy X 2040?"],
                        "reason": "fictional no-answer",
                        "status": "needs_label_review",
                    }
                ],
            )
            self._write_jsonl(
                labels_path,
                [
                    {
                        "candidate_id": "candidate_no_answer_007",
                        "decision": "accept_as_gold",
                        "gold_id": "no_answer_007_reviewed",
                        "question": "Any news about fictional policy X 2040?",
                        "turns": None,
                        "expected_route": "default",
                        "gold_evidence_ids": [],
                        "should_answer": False,
                        "should_refuse": True,
                        "must_have_citations": False,
                        "case_type": "G_no_answer",
                        "notes": "Reviewed manually as an unsupported no-answer case.",
                    }
                ],
            )

            result = validate_reviewed_labels(candidates_path, labels_path)

        self.assertTrue(result.ok)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.errors, [])
