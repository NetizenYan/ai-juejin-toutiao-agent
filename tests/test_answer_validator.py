import unittest

from harness.answer_contract import AnswerContract
from harness.answer_validator import (
    asks_investment_certainty,
    declines_to_answer,
    extract_citations,
    is_refusal,
    quoted_term_supported,
    validate_answer,
)


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

    def test_long_answer_with_refusal_phrase_is_not_treated_as_refusal(self):
        answer = (
            "据悉，新质生产力相关政策将在明年全面落地，预计带动制造业投资大幅增长，"
            "多个地区已经出台配套补贴措施，龙头企业订单同比明显增加，行业景气度持续上行，"
            "市场普遍预期相关产业链将迎来新一轮扩张周期，具体细节站内未找到更多报道，可以换个关键词再试。"
        )

        self.assertFalse(is_refusal(answer))
        result = validate_answer(answer, self._contract(), self._evidence())
        self.assertFalse(result.passed)
        self.assertIn("missing_citation", result.constraint_violations)

    def test_cited_answer_mentioning_not_found_is_not_a_refusal(self):
        self.assertFalse(is_refusal("站内未找到更多细节，但已有报道提到高质量发展取得新进展。[news:2726]"))

    def test_short_refusal_is_still_recognized(self):
        self.assertTrue(is_refusal("站内未找到可靠新闻证据，建议换个关键词再试。"))
        self.assertTrue(is_refusal("我查了站内新闻，但没有找到足够匹配的内容，你可以换个关键词再试。"))

    def test_quoted_query_term_not_supported_by_evidence_fails_non_refusal(self):
        result = validate_answer(
            "站内有相关报道提到该政策。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="站内有没有关于虚构政策“蓝鲸计划2029”的新闻？",
        )

        self.assertFalse(result.passed)
        self.assertIn("evidence_not_support_query", result.constraint_violations)

    def test_partial_answer_that_says_the_named_plan_was_not_found_is_kept(self):
        answer = (
            "“夏季经济刺激计划”的总规模，站内未找到可靠新闻证据。\n"
            "- 报道提到该政策推动高质量发展 [news:jjrb:8dcc9e6349959132]。"
        )

        result = validate_answer(answer, self._contract(), self._evidence(),
                                 query="印尼推出的“夏季经济刺激计划”总规模多少？")

        self.assertNotIn("evidence_not_support_query", result.constraint_violations)

    def test_naming_the_plan_as_fact_anywhere_still_fails(self):
        answer = (
            "“夏季经济刺激计划”的总规模站内未找到。\n"
            "- “夏季经济刺激计划”已经全面落地 [news:jjrb:8dcc9e6349959132]。"
        )

        result = validate_answer(answer, self._contract(), self._evidence(),
                                 query="印尼推出的“夏季经济刺激计划”总规模多少？")

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

    def test_detects_investment_certainty_phrasings_beyond_fixed_terms(self):
        for query in (
            "新质生产力是不是必然带动半导体股票上涨？",
            "根据这些新质生产力报道，能不能直接推荐几只最值得买的股票？",
            "相关政策是不是能保证科技基金收益上涨？",
            "如果只看经济日报的报道，应该加仓哪些行业基金？",
        ):
            self.assertTrue(asks_investment_certainty(query), query)
        for query in (
            "新质生产力对半导体板块可能有什么影响？请保守表达并带引用。",
            "最近高质量发展和新质生产力有什么新闻？",
            "推荐几篇新质生产力的文章",
        ):
            self.assertFalse(asks_investment_certainty(query), query)

    def test_declining_to_recommend_stocks_counts_as_guard(self):
        result = validate_answer(
            "无法直接推荐股票，相关报道主要讲新质生产力推动高质量发展。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="根据这些报道，能不能直接推荐几只最值得买的股票？",
        )

        self.assertTrue(result.passed)

    def test_advice_wording_is_blocked_even_when_not_asked(self):
        result = validate_answer(
            "制造业加快升级，建议买入相关龙头。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="新质生产力如何影响制造业？",
        )

        self.assertFalse(result.passed)
        self.assertIn("investment_advice_or_certainty", result.constraint_violations)

    def test_non_investment_answer_needs_no_disclaimer(self):
        result = validate_answer(
            "新质生产力推动制造业升级。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="新质生产力如何影响制造业？",
        )

        self.assertTrue(result.passed)

    def test_stated_advice_fails_even_with_disclaimer(self):
        result = validate_answer(
            "以下不构成投资建议。建议买入相关龙头。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
            query="新质生产力对半导体有什么影响？",
        )

        self.assertIn("investment_advice_or_certainty", result.constraint_violations)

    def test_negated_or_quoted_terms_are_not_advice(self):
        for answer in (
            "并不必然带动股价，不一定利好，也不建议买入。[news:jjrb:8dcc9e6349959132]",
            "站内未找到表明“一定利好半导体”的证据，不能据此判断。[news:jjrb:8dcc9e6349959132]",
        ):
            result = validate_answer(answer, self._contract(), self._evidence(), query="这些政策是不是一定利好半导体？")
            self.assertTrue(result.passed, (answer, result.constraint_violations))

    def test_long_explained_refusal_declines_but_is_not_a_passing_refusal(self):
        answer = ("站内未找到可靠新闻证据，无法确认《新闻联播》在最近一周报道了哪些具体重大会议。"
                  "建议您换一个更精确的时间范围或会议名称关键词再试。")
        self.assertTrue(declines_to_answer(answer))
        self.assertFalse(is_refusal(answer))
        self.assertFalse(declines_to_answer("相关报道聚焦制造业 [news:jjrb:1]，站内未找到更多报道。"))

    def test_shadow_failed_result_records_would_rewrite_without_rewrite_count(self):
        result = validate_answer("最近报道主要关注新质生产力。", self._contract(), self._evidence())

        metadata = result.to_metadata(mode="shadow", rewrite_count=0)

        self.assertFalse(metadata["passed"])
        self.assertTrue(metadata["wouldRewrite"])
        self.assertEqual(metadata["rewriteCount"], 0)
        self.assertEqual(metadata["mode"], "shadow")

    def test_number_missing_from_evidence_fails(self):
        result = validate_answer(
            "相关报道提到新质生产力，另有2030年数据预测。[news:jjrb:8dcc9e6349959132]",
            self._contract(),
            self._evidence(),
        )

        self.assertFalse(result.passed)
        self.assertIn("unsupported_number_or_date", result.constraint_violations)
        self.assertEqual(result.unsupported_numbers, ["2030"])

    def test_publish_date_query_numbers_and_percent_forms_are_supported(self):
        evidence = [{"ref": "news:jjrb:1", "title": "高技术制造业增长", "snippet": "增加值同比增长12.5%",
                     "publish_time": "2026-03-16 00:00:00"}]
        result = validate_answer(
            "这篇报道发布于2026年3月16日，高技术制造业增长12.5 [news:jjrb:1]，回应了2027年的问题。",
            self._contract(),
            evidence,
            query="2027年目标和高技术制造业有什么报道？",
        )

        self.assertTrue(result.passed, result.constraint_violations)


def _plain_contract():
    return AnswerContract(
        style="plain_language", detail_level="brief", max_points=3, max_chars=None,
        must_include_citations=True, citation_style="[news:ID]", evidence_only=True, requires_evidence=True,
        allow_background=True, background_policy="one_sentence_plain_explanation",
        no_answer_policy="refuse_with_suggestion",
    )


class QuotedTermTests(unittest.TestCase):
    def test_a_quoted_name_reported_without_the_askers_qualifier_is_supported(self):
        evidence = [{"ref": "news:jjrb:1", "title": "印尼推出经济刺激计划改善预期",
                     "snippet": "计划为7930万户家庭提供50%的电费折扣。"}]

        result = validate_answer("这项经济刺激计划为7930万户家庭提供50%的电费折扣 [news:jjrb:1]。", _plain_contract(),
                                 evidence, query="印尼“夏季经济刺激计划”惠及多少户家庭？")

        self.assertNotIn("evidence_not_support_query", result.constraint_violations)

    def test_a_name_sharing_only_a_short_part_with_the_evidence_is_not(self):
        self.assertFalse(quoted_term_supported("蓝鲸计划", "鲸计划"))
        self.assertFalse(quoted_term_supported("云杉智能农机挑战赛", "智能农机补贴政策出台"))
        self.assertTrue(quoted_term_supported("夏季经济刺激计划", "印尼推出经济刺激计划"))


class MagnitudeTests(unittest.TestCase):
    def test_a_figure_under_another_magnitude_is_unsupported(self):
        evidence = [{"ref": "news:jjrb:1", "title": "水果产业", "snippet": "2024年我国水果总产量为3.35亿吨。"}]

        result = validate_answer("2024年水果总产量3.35亿吨（约3.35万亿公斤）[news:jjrb:1]。", _plain_contract(), evidence)

        self.assertIn("3.35万亿", result.unsupported_numbers)
        self.assertFalse(result.passed)

    def test_the_reported_magnitude_passes(self):
        evidence = [{"ref": "news:jjrb:1", "title": "水果产业", "snippet": "2024年我国水果总产量为3.35亿吨。"}]

        result = validate_answer("2024年水果总产量为3.35亿吨 [news:jjrb:1]。", _plain_contract(), evidence)

        self.assertEqual(result.unsupported_numbers, [])


if __name__ == "__main__":
    unittest.main()
