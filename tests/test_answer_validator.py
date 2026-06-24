import unittest

from harness.answer_contract import AnswerContract
from harness.answer_validator import extract_citations, validate_answer


class AnswerValidatorTests(unittest.TestCase):
    def _contract(self, max_chars=None):
        return AnswerContract(
            style="plain_language",
            detail_level="brief",
            max_points=3,
            max_chars=max_chars,
            must_include_citations=True,
            citation_style="[news:ID]",
            evidence_only=True,
            requires_evidence=True,
            allow_background=True,
            background_policy="one_sentence_plain_explanation",
            no_answer_policy="refuse_with_suggestion",
        )

    def _evidence(self):
        return [
            {
                "ref": "news:jjrb:8dcc9e6349959132",
                "title": "进一步深化对新质生产力的认识",
                "snippet": "新质生产力是推动高质量发展的重要动力。",
            },
            {
                "ref": "news:2726",
                "title": "高质量发展取得新进展",
                "snippet": "经济运行稳中有进。",
            },
        ]

    def test_extracts_supported_news_citation_formats(self):
        text = "[news:2726] [news:jjrb:8dcc9e6349959132] [news:cctv-20200101-3]"

        self.assertEqual(
            extract_citations(text),
            ["news:2726", "news:jjrb:8dcc9e6349959132", "news:cctv-20200101-3"],
        )

    def test_missing_citation_fails_when_evidence_answer_is_required(self):
        result = validate_answer("最近报道主要关注新质生产力。", self._contract(), self._evidence())

        self.assertFalse(result.passed)
        self.assertIn("missing_citation", result.constraint_violations)

    def test_invalid_citation_fails(self):
        result = validate_answer("最近报道主要关注新质生产力。[news:missing]", self._contract(), self._evidence())

        self.assertFalse(result.passed)
        self.assertEqual(result.invalid_refs, ["news:missing"])

    def test_max_chars_counts_final_answer_text_with_citation_tolerance(self):
        answer = "a" * 127

        result = validate_answer(answer, self._contract(max_chars=120), self._evidence())

        self.assertFalse(result.passed)
        self.assertIn("max_chars_exceeded", result.constraint_violations)

    def test_max_chars_allows_five_percent_tolerance(self):
        answer = "a" * 126

        result = validate_answer(answer, self._contract(max_chars=120), self._evidence())

        self.assertNotIn("max_chars_exceeded", result.constraint_violations)

    def test_large_evidence_copy_fails(self):
        copied = "新质生产力是推动高质量发展的重要动力。" * 3
        result = validate_answer(copied + "[news:jjrb:8dcc9e6349959132]", self._contract(), self._evidence())

        self.assertFalse(result.passed)
        self.assertIn("large_evidence_copy", result.constraint_violations)

    def test_no_answer_refusal_is_valid_without_citation(self):
        result = validate_answer("站内未找到可靠新闻证据，建议换个关键词再试。", self._contract(), [])

        self.assertTrue(result.passed)
        self.assertEqual(result.hallucination_risk, "low")
        self.assertEqual(result.constraint_violations, [])

    def test_refusal_is_valid_when_evidence_does_not_support_question(self):
        result = validate_answer("站内未找到可靠新闻证据，建议换个关键词再试。", self._contract(), self._evidence())

        self.assertTrue(result.passed)
        self.assertEqual(result.hallucination_risk, "low")

    def test_quoted_query_term_not_supported_by_evidence_fails_non_refusal(self):
        result = validate_answer(
            "站内有相关报道提到该政策。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="站内有没有关于虚构政策“蓝鲸计划2029”的新闻？",
        )

        self.assertFalse(result.passed)
        self.assertIn("evidence_not_support_query", result.constraint_violations)

    def test_unquoted_named_plan_not_supported_by_evidence_fails_non_refusal(self):
        result = validate_answer(
            "相关报道显示蓝鲸计划2029已经落地。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="刚才那个政策是不是说明蓝鲸计划2029已经落地？",
        )

        self.assertFalse(result.passed)
        self.assertIn("evidence_not_support_query", result.constraint_violations)

    def test_unquoted_named_act_not_supported_by_evidence_fails_non_refusal(self):
        result = validate_answer(
            "近期相关报道提到星河制造业跃迁法案2040已经落地。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="站内有没有关于星河制造业跃迁法案2040的消息？",
        )

        self.assertFalse(result.passed)
        self.assertIn("evidence_not_support_query", result.constraint_violations)

    def test_investment_certainty_question_requires_conservative_guard(self):
        result = validate_answer(
            "近期相关报道主要聚焦新质生产力。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="那这个是不是一定利好半导体？",
        )

        self.assertFalse(result.passed)
        self.assertIn("missing_investment_guard", result.constraint_violations)

    def test_investment_certainty_question_allows_conservative_answer(self):
        result = validate_answer(
            "不能判断一定利好半导体，只能说相关政策可能影响产业升级，仍需结合行情和基本面判断。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="那这个是不是一定利好半导体？",
        )

        self.assertTrue(result.passed)

    def test_shadow_failed_result_records_would_rewrite_without_rewrite_count(self):
        result = validate_answer("最近报道主要关注新质生产力。", self._contract(), self._evidence())

        metadata = result.to_metadata(mode="shadow", rewrite_count=0)

        self.assertFalse(metadata["passed"])
        self.assertTrue(metadata["wouldRewrite"])
        self.assertEqual(metadata["rewriteCount"], 0)
        self.assertEqual(metadata["mode"], "shadow")

    def test_unsupported_claim_is_warning_not_hard_fail(self):
        result = validate_answer(
            "相关报道提到新质生产力，另有2030年数据预测。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
        )

        self.assertTrue(result.passed)
        self.assertIn("possible_unsupported_number_or_date", result.risk_reasons)


if __name__ == "__main__":
    unittest.main()
