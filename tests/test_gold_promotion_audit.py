import json
import tempfile
import unittest
from pathlib import Path


class GoldPromotionAuditTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_audit_blocks_when_official_reviewed_labels_are_empty_but_draft_exists(self):
        try:
            from scripts.audit_gold_promotion_readiness import audit_promotion_readiness
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_promotion_readiness should exist")

        gold_rows = [{"id": "a1", "case_type": "A_exact_news_qa"}]
        candidate_rows = [{"id": "candidate_a2", "case_type": "A_exact_news_qa"}]
        official_labels: list[dict] = []
        draft_labels = [
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
                "notes": "Reviewed draft.",
            }
        ]

        audit = audit_promotion_readiness(
            gold_rows,
            candidate_rows,
            official_labels,
            draft_labels,
            targets={"A_exact_news_qa": 2},
            target_total=2,
        )

        self.assertFalse(audit["formal_promotion_ready"])
        self.assertEqual(audit["official"]["label_count"], 0)
        self.assertEqual(audit["draft"]["label_count"], 1)
        self.assertIn("official reviewed labels are empty", audit["blockers"])
        self.assertIn("draft labels exist but have not been copied into the official reviewed-label file", audit["warnings"])

    def test_audit_allows_formal_promotion_when_official_labels_are_valid_and_cover_targets(self):
        try:
            from scripts.audit_gold_promotion_readiness import audit_promotion_readiness
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_promotion_readiness should exist")

        gold_rows = [{"id": "a1", "case_type": "A_exact_news_qa"}]
        candidate_rows = [{"id": "candidate_a2", "case_type": "A_exact_news_qa"}]
        official_labels = [
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
                "notes": "Reviewed official.",
            }
        ]

        audit = audit_promotion_readiness(
            gold_rows,
            candidate_rows,
            official_labels,
            [],
            targets={"A_exact_news_qa": 2},
            target_total=2,
        )

        self.assertTrue(audit["formal_promotion_ready"])
        self.assertEqual(audit["official"]["accepted_count"], 1)
        self.assertEqual(audit["official"]["projected_formal_count"], 2)
        self.assertEqual(audit["blockers"], [])

    def test_write_audit_outputs_json_and_markdown(self):
        try:
            from scripts.audit_gold_promotion_readiness import write_promotion_audit
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_promotion_readiness should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            candidates = root / "candidates.jsonl"
            official = root / "official.jsonl"
            draft = root / "draft.jsonl"
            report = root / "audit.md"
            json_report = root / "audit.json"
            self._write_jsonl(gold, [{"id": "a1", "case_type": "A_exact_news_qa"}])
            self._write_jsonl(candidates, [{"id": "candidate_a2", "case_type": "A_exact_news_qa"}])
            self._write_jsonl(official, [])
            self._write_jsonl(
                draft,
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
                        "notes": "Reviewed draft.",
                    }
                ],
            )

            audit = write_promotion_audit(
                gold,
                candidates,
                official,
                draft,
                report,
                json_report,
                targets={"A_exact_news_qa": 2},
                target_total=2,
            )

            self.assertFalse(audit["formal_promotion_ready"])
            self.assertTrue(report.exists())
            self.assertTrue(json_report.exists())
            self.assertIn("official reviewed labels are empty", report.read_text(encoding="utf-8"))
