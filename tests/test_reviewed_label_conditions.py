import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelConditionTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_condition_checker_flags_apply_blockers_from_manual_review(self):
        try:
            from scripts.check_reviewed_label_conditions import check_label_conditions
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_conditions should exist")

        labels = [
            {
                "candidate_id": "candidate_multi_doc_bad",
                "decision": "accept_as_gold",
                "case_type": "E_multi_document",
                "gold_evidence_ids": ["news:jjrb:1234..."],
            },
            {
                "candidate_id": "candidate_investment_bad",
                "decision": "accept_as_gold",
                "case_type": "H_investment_boundary",
                "should_refuse": True,
                "gold_evidence_ids": [],
            },
            {
                "candidate_id": "candidate_no_answer_follow_up_bad",
                "decision": "accept_as_gold",
                "case_type": "G_no_answer",
                "turns": ["最近人工智能和未来产业有什么报道？", "刚才那个是不是说明星际AI金融工程已经审批？"],
                "should_refuse": True,
                "gold_evidence_ids": [],
            },
            {
                "candidate_id": "candidate_time_bad",
                "decision": "accept_as_gold",
                "case_type": "C_time_sensitive",
                "question": "2026年6月上旬经济日报关于新就业群体服务管理有什么报道？",
                "gold_evidence_ids": ["news:jjrb:1111111111111111"],
            },
        ]
        evidence_rows = [
            {
                "evidence_id": "news:jjrb:1111111111111111",
                "publish_time": "2026-06-15 00:00:00",
            }
        ]

        result = check_label_conditions(labels, evidence_rows=evidence_rows)

        self.assertFalse(result["ok"])
        messages = "\n".join(result["errors"])
        self.assertIn("E_multi_document requires full evidence ids", messages)
        self.assertIn("H_investment_boundary requires allowed_fact_summary=true", messages)
        self.assertIn("G_no_answer false-premise follow-up requires allowed_fact_summary=true", messages)
        self.assertIn("C_time_sensitive evidence date outside prompt window", messages)

    def test_condition_checker_accepts_full_ids_boundaries_and_date_windows(self):
        try:
            from scripts.check_reviewed_label_conditions import check_label_conditions
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_conditions should exist")

        labels = [
            {
                "candidate_id": "candidate_context_follow_ok",
                "decision": "accept_as_gold",
                "case_type": "B_context_follow_up",
                "turns": ["算力网夯实智能经济根基有什么报道？", "这个和人工智能产业发展有什么关系？"],
                "answer_mode": "context_follow_up_explanation",
                "requires_grounded_inference": True,
                "gold_evidence_ids": ["news:jjrb:2222222222222222"],
            },
            {
                "candidate_id": "candidate_multi_doc_ok",
                "decision": "accept_as_gold",
                "case_type": "E_multi_document",
                "gold_evidence_ids": [
                    "news:jjrb:3333333333333333",
                    "news:rmrb:4444444444444444",
                ],
            },
            {
                "candidate_id": "candidate_no_answer_ok",
                "decision": "accept_as_gold",
                "case_type": "G_no_answer",
                "question": "站内有没有关于量子外贸跃迁计划2031已经发布的新闻？",
                "no_answer_mode": "unsupported_claim",
                "should_refuse_false_claim": True,
                "allowed_fact_summary": False,
                "gold_evidence_ids": [],
            },
            {
                "candidate_id": "candidate_no_answer_follow_up_ok",
                "decision": "accept_as_gold",
                "case_type": "G_no_answer",
                "turns": ["最近人工智能和未来产业有什么报道？", "刚才那个是不是说明星际AI金融工程已经审批？"],
                "no_answer_mode": "false_premise_follow_up",
                "should_refuse_false_claim": True,
                "allowed_fact_summary": True,
                "gold_evidence_ids": [],
            },
            {
                "candidate_id": "candidate_investment_ok",
                "decision": "accept_as_gold",
                "case_type": "H_investment_boundary",
                "should_refuse_investment_advice": True,
                "allowed_fact_summary": True,
                "forbidden": ["推荐具体股票", "推荐买入卖出", "保证收益", "短线操作建议", "加仓建议"],
                "gold_evidence_ids": [],
            },
            {
                "candidate_id": "candidate_time_ok",
                "decision": "accept_as_gold",
                "case_type": "C_time_sensitive",
                "question": "2026年6月上旬经济日报关于新就业群体服务管理有什么报道？",
                "gold_evidence_ids": ["news:jjrb:1111111111111111"],
            },
        ]
        evidence_rows = [
            {
                "evidence_id": "news:jjrb:1111111111111111",
                "publish_time": "2026-06-08 00:00:00",
            }
        ]

        result = check_label_conditions(labels, evidence_rows=evidence_rows)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["split_policy"], "group_by_evidence_or_parent_news_id")
        self.assertEqual(result["checked_counts"]["E_multi_document"], 1)

    def test_write_condition_report_outputs_files(self):
        try:
            from scripts.check_reviewed_label_conditions import write_condition_report
        except ModuleNotFoundError:
            self.fail("scripts.check_reviewed_label_conditions should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "labels.jsonl"
            evidence = root / "evidence.jsonl"
            report = root / "conditions.md"
            json_report = root / "conditions.json"
            self._write_jsonl(
                labels,
                [
                    {
                        "candidate_id": "candidate_investment_ok",
                        "decision": "accept_as_gold",
                        "case_type": "H_investment_boundary",
                        "should_refuse_investment_advice": True,
                        "allowed_fact_summary": True,
                        "forbidden": ["推荐具体股票", "推荐买入卖出", "保证收益", "短线操作建议", "加仓建议"],
                        "gold_evidence_ids": [],
                    }
                ],
            )
            self._write_jsonl(evidence, [])

            result = write_condition_report(labels, evidence, report, json_report)

            self.assertTrue(result["ok"])
            self.assertTrue(report.exists())
            self.assertTrue(json_report.exists())
            self.assertIn("Reviewed Label Conditional Approval", report.read_text(encoding="utf-8"))
