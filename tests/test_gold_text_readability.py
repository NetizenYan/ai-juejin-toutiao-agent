import json
import tempfile
import unittest
from pathlib import Path


class GoldTextReadabilityTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_summarizes_cjk_prompt_readability(self):
        try:
            from scripts.audit_gold_text_readability import summarize_readability
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_text_readability should exist")

        summary = summarize_readability(
            [
                {
                    "candidate_id": "candidate_a1",
                    "question": "最近新质生产力有什么新闻？",
                    "case_type": "A_exact_news_qa",
                }
            ]
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(summary["rows_with_cjk"], 1)
        self.assertEqual(summary["rows_without_text"], 0)
        self.assertEqual(summary["replacement_char_rows"], 0)

    def test_flags_missing_text_and_replacement_characters(self):
        try:
            from scripts.audit_gold_text_readability import summarize_readability
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_text_readability should exist")

        summary = summarize_readability(
            [
                {"candidate_id": "candidate_empty", "case_type": "A_exact_news_qa"},
                {
                    "candidate_id": "candidate_bad",
                    "question": "新质生产力�",
                    "case_type": "A_exact_news_qa",
                },
            ]
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["rows_without_text"], 1)
        self.assertEqual(summary["replacement_char_rows"], 1)
        self.assertIn("candidate_empty", summary["problem_rows"][0]["row_id"])
        self.assertIn("candidate_bad", summary["problem_rows"][1]["row_id"])

    def test_flags_common_utf8_as_gbk_mojibake_markers(self):
        try:
            from scripts.audit_gold_text_readability import summarize_readability
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_text_readability should exist")

        summary = summarize_readability(
            [
                {
                    "candidate_id": "candidate_mojibake",
                    "question": "缁忔祹鏃ユ姤锛屾柊璐ㄧ敓浜у姏鏈変粈涔堟柊闂伙紵",
                    "case_type": "A_exact_news_qa",
                }
            ]
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["mojibake_suspect_rows"], 1)
        self.assertIn("prompt has mojibake-like marker patterns", summary["problem_rows"][0]["problems"])

    def test_uses_candidate_fallback_text_for_merge_label_rows(self):
        try:
            from scripts.audit_gold_text_readability import summarize_readability
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_text_readability should exist")

        summary = summarize_readability(
            [
                {
                    "candidate_id": "candidate_merge",
                    "decision": "merge_with_existing",
                    "case_type": "B_context_follow_up",
                }
            ],
            fallback_rows=[
                {
                    "id": "candidate_merge",
                    "query_or_turns": ["最近新质生产力有什么新闻？", "它对制造业有什么影响？"],
                    "case_type": "B_context_follow_up",
                }
            ],
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["rows_with_text"], 1)
        self.assertEqual(summary["rows_with_cjk"], 1)
        self.assertEqual(summary["rows_without_text"], 0)

    def test_write_readability_audit_outputs_markdown_and_json(self):
        try:
            from scripts.audit_gold_text_readability import write_readability_audit
        except ModuleNotFoundError:
            self.fail("scripts.audit_gold_text_readability should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "labels.jsonl"
            report = root / "readability.md"
            json_report = root / "readability.json"
            self._write_jsonl(
                source,
                [
                    {
                        "candidate_id": "candidate_a1",
                        "question": "最近新质生产力有什么新闻？",
                        "case_type": "A_exact_news_qa",
                    }
                ],
            )

            summary = write_readability_audit(source, report, json_report)

            self.assertTrue(summary["ok"])
            self.assertTrue(report.exists())
            self.assertTrue(json_report.exists())
            self.assertIn("Gold Text Readability Audit", report.read_text(encoding="utf-8"))
