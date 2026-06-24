import unittest

from harness.answer_contract import (
    build_answer_contract,
    parse_enforce_routes,
    resolve_validation_mode,
)
from harness.query_understanding import understand_user_query


class AnswerContractTests(unittest.TestCase):
    def test_news_qa_requires_evidence_and_citations_by_default(self):
        contract = build_answer_contract(
            understand_user_query("最近高质量发展有什么新闻？"),
            intent="news_qa",
        )

        self.assertTrue(contract.requires_evidence)
        self.assertTrue(contract.must_include_citations)
        self.assertEqual(contract.style, "plain_language")
        self.assertEqual(contract.detail_level, "brief")
        self.assertEqual(contract.max_points, 3)

    def test_general_chat_does_not_require_news_evidence(self):
        contract = build_answer_contract(
            understand_user_query("你好，介绍一下你自己"),
            intent="general_chat",
        )

        self.assertFalse(contract.requires_evidence)
        self.assertFalse(contract.must_include_citations)

    def test_user_max_chars_overrides_default_none(self):
        contract = build_answer_contract(
            understand_user_query("最近经济新闻，不超过120字"),
            intent="news_qa",
        )

        self.assertEqual(contract.max_chars, 120)

    def test_enforce_routes_parse_csv_with_trim_and_empty_values(self):
        routes = parse_enforce_routes(" econ_finance_query, ,policy_query, ")

        self.assertEqual(routes, {"econ_finance_query", "policy_query"})

    def test_validation_mode_priority(self):
        enforce_routes = {"econ_finance_query", "policy_query"}

        self.assertEqual(resolve_validation_mode(False, "shadow", enforce_routes, "econ_finance_query"), "off")
        self.assertEqual(resolve_validation_mode(True, "shadow", enforce_routes, "econ_finance_query"), "enforce")
        self.assertEqual(resolve_validation_mode(True, "shadow", enforce_routes, "finance"), "shadow")
        self.assertEqual(resolve_validation_mode(True, "enforce", enforce_routes, "finance"), "enforce")

    def test_enforce_routes_use_exact_match(self):
        enforce_routes = {"econ_finance_query"}

        self.assertEqual(resolve_validation_mode(True, "shadow", enforce_routes, "econ_finance_query_extra"), "shadow")


if __name__ == "__main__":
    unittest.main()
