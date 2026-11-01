"""Reports the reranker scores as unrelated are not dressed up as a title template."""
import unittest
from dataclasses import replace

from harness import agent
from harness.answer_contract import AnswerContract
from tests.test_rule_requests import ITEM, _run

UNRELATED = {**ITEM, "cross_encoder_score": 0.004}
RELATED = {**ITEM, "cross_encoder_score": 0.97}


def _results(*items):
    return [{"tool": "retrieve_news", "items": list(items)}]


class GateTests(unittest.TestCase):
    def test_relevance_needs_a_score_on_every_report(self):
        self.assertTrue(agent._evidence_unrelated(_results(UNRELATED)))
        self.assertFalse(agent._evidence_unrelated(_results(UNRELATED, RELATED)))
        self.assertFalse(agent._evidence_unrelated(_results(ITEM)))      # reranker unavailable: no judgement
        self.assertFalse(agent._evidence_unrelated([]))

    def test_no_title_template_from_unrelated_reports(self):
        contract = AnswerContract()

        self.assertEqual(agent._deterministic_evidence_answer(_results(UNRELATED), contract, "科创板"),
                         agent._no_answer_response())
        self.assertIn("近期相关报道主要聚焦", agent._deterministic_evidence_answer(_results(RELATED), contract, "科创板"))

    def test_parent_aggregation_keeps_the_best_cross_encoder_score(self):
        chunks = [{**ITEM, "rerank_score": 0.9, "cross_encoder_score": 0.2}, {**ITEM, "rerank_score": 0.5, "cross_encoder_score": 0.6}]

        self.assertEqual(agent._aggregate_parents(chunks, 5)[0]["cross_encoder_score"], 0.6)


class RunChatTests(unittest.TestCase):
    def test_a_set_up_message_gets_a_note_instead_of_try_other_keywords(self):
        setup = _run([{"role": "user", "content": "我们为一个虚构新闻台制作 staging 页面。"}],
                     "站内未找到可靠新闻证据，建议换个关键词再试。", [UNRELATED])

        self.assertEqual(setup, agent.NOT_A_QUESTION_REPLY)

    def test_questions_and_requests_keep_the_refusal(self):
        for text in ("科创板今年新增了多少家上市公司", "请查一下科创板新股发行情况。"):
            answer = _run([{"role": "user", "content": text}], "站内未找到可靠新闻证据，建议换个关键词再试。", [UNRELATED])
            self.assertEqual(answer, "站内未找到可靠新闻证据，建议换个关键词再试。", text)


if __name__ == "__main__":
    unittest.main()
