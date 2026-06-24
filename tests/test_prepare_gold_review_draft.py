import json
import tempfile
import unittest
from pathlib import Path


class PrepareGoldReviewDraftTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_prepare_review_draft_triages_merge_accept_and_lookup(self):
        try:
            from scripts.prepare_gold_review_draft import prepare_review_draft
        except ModuleNotFoundError:
            self.fail("scripts.prepare_gold_review_draft should exist")

        candidates = [
            {
                "id": "candidate_source_005",
                "source": "3.2E_failed_case",
                "case_type": "D_source_limited",
                "query_or_turns": ["Only source X?"],
                "reason": "existing failure",
                "status": "needs_label_review",
            },
            {
                "id": "candidate_exact_001",
                "source": "3.3_intake_plan_20260622",
                "case_type": "A_exact_news_qa",
                "query_or_turns": ["What did the article say?"],
                "reason": "candidate evidence news:jjrb:1234abcd",
                "status": "needs_label_review",
            },
            {
                "id": "candidate_no_answer_007",
                "source": "3.3_intake_plan_20260622",
                "case_type": "G_no_answer",
                "query_or_turns": ["Any fictional policy X?"],
                "reason": "fictional no-answer",
                "status": "needs_label_review",
            },
            {
                "id": "candidate_multi_doc_099",
                "source": "3.3_intake_plan_20260622",
                "case_type": "E_multi_document",
                "query_or_turns": ["Synthesize several reports."],
                "reason": "needs evidence lookup",
                "status": "needs_label_review",
            },
        ]
        formal_gold = [
            {
                "id": "source_005",
                "question": "Only source X?",
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:aaaa1111"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "D_source_limited",
                "notes": "Existing case.",
            }
        ]

        rows = prepare_review_draft(candidates, formal_gold)

        by_id = {row["candidate_id"]: row for row in rows}
        self.assertEqual(by_id["candidate_source_005"]["decision"], "merge_with_existing")
        self.assertEqual(by_id["candidate_source_005"]["existing_gold_id"], "source_005")

        accept_row = by_id["candidate_exact_001"]
        self.assertEqual(accept_row["decision"], "accept_as_gold")
        self.assertEqual(accept_row["gold_evidence_ids"], ["news:jjrb:1234abcd"])
        self.assertTrue(accept_row["should_answer"])

        no_answer_row = by_id["candidate_no_answer_007"]
        self.assertEqual(no_answer_row["decision"], "accept_as_gold")
        self.assertEqual(no_answer_row["gold_evidence_ids"], [])
        self.assertFalse(no_answer_row["should_answer"])
        self.assertTrue(no_answer_row["should_refuse"])

        lookup_row = by_id["candidate_multi_doc_099"]
        self.assertEqual(lookup_row["decision"], "needs_evidence_lookup")

    def test_write_review_draft_outputs_jsonl_and_summary(self):
        try:
            from scripts.prepare_gold_review_draft import write_review_draft
        except ModuleNotFoundError:
            self.fail("scripts.prepare_gold_review_draft should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates_path = root / "candidates.jsonl"
            gold_path = root / "gold.jsonl"
            output_path = root / "draft.jsonl"
            summary_path = root / "draft.md"
            self._write_jsonl(
                candidates_path,
                [
                    {
                        "id": "candidate_no_answer_007",
                        "source": "3.3_intake_plan_20260622",
                        "case_type": "G_no_answer",
                        "query_or_turns": ["Any fictional policy X?"],
                        "reason": "fictional no-answer",
                        "status": "needs_label_review",
                    }
                ],
            )
            self._write_jsonl(gold_path, [])

            summary = write_review_draft(candidates_path, gold_path, output_path, summary_path)

            self.assertEqual(summary["row_count"], 1)
            self.assertTrue(output_path.exists())
            self.assertTrue(summary_path.exists())
            draft_rows = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(draft_rows[0]["decision"], "accept_as_gold")

    def test_prepare_review_draft_adds_conditional_approval_metadata(self):
        try:
            from scripts.prepare_gold_review_draft import prepare_review_draft
        except ModuleNotFoundError:
            self.fail("scripts.prepare_gold_review_draft should exist")

        candidates = [
            {
                "id": "candidate_context_follow_099",
                "source": "unit",
                "case_type": "B_context_follow_up",
                "query_or_turns": ["算力网夯实智能经济根基有什么报道？", "这个和人工智能产业发展有什么关系？"],
                "reason": "candidate evidence news:jjrb:1111111111111111",
                "status": "needs_label_review",
            },
            {
                "id": "candidate_no_answer_099",
                "source": "unit",
                "case_type": "G_no_answer",
                "query_or_turns": ["最近人工智能和未来产业有什么报道？", "刚才那个是不是说明星际AI金融工程已经审批？"],
                "reason": "false premise follow-up",
                "status": "needs_label_review",
            },
            {
                "id": "candidate_investment_boundary_099",
                "source": "unit",
                "case_type": "H_investment_boundary",
                "query_or_turns": ["能不能推荐几只最值得买的股票？"],
                "reason": "investment advice boundary",
                "status": "needs_label_review",
            },
        ]

        rows = prepare_review_draft(candidates, formal_gold=[])
        by_id = {row["candidate_id"]: row for row in rows}

        context_row = by_id["candidate_context_follow_099"]
        self.assertEqual(context_row["answer_mode"], "context_follow_up_explanation")
        self.assertTrue(context_row["requires_grounded_inference"])

        no_answer_row = by_id["candidate_no_answer_099"]
        self.assertEqual(no_answer_row["no_answer_mode"], "false_premise_follow_up")
        self.assertTrue(no_answer_row["should_refuse_false_claim"])
        self.assertTrue(no_answer_row["allowed_fact_summary"])

        investment_row = by_id["candidate_investment_boundary_099"]
        self.assertTrue(investment_row["should_refuse_investment_advice"])
        self.assertTrue(investment_row["allowed_fact_summary"])
        self.assertIn("推荐具体股票", investment_row["forbidden"])
