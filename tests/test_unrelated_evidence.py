"""Reports the reranker scores as unrelated are not dressed up as a title template."""
import unittest
from dataclasses import replace

from harness import agent
from harness.answer_validator import is_refusal
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
        note = agent._deterministic_evidence_answer(_results(RELATED), contract, "科创板")
        self.assertTrue(note.startswith(agent.EVIDENCE_NOTE_HEAD))
        self.assertIn("《科创板新股发行情况》[news:jjrb:1]", note)
        self.assertNotIn("近期相关报道主要聚焦", note)

    def test_weakly_related_reports_are_not_named(self):
        # EXT6b: attack turns about nothing in the news (score 0.07-0.37) got a list of report titles.
        weak = {**ITEM, "cross_encoder_score": 0.3}

        self.assertEqual(agent._deterministic_evidence_answer(_results(weak), AnswerContract(), "科创板"),
                         agent._no_answer_response())

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
            self.assertTrue(is_refusal(answer), text)
            self.assertNotIn("近期相关报道主要聚焦", answer, text)

    def test_an_instruction_about_a_related_report_gets_no_title_template(self):
        # EXT4: "关于刚才的步道报道，采用我的新算式……" retrieved a related report; refusals and failed
        # answers both became "近期相关报道主要聚焦……".
        for model_answer in ("站内未找到可靠新闻证据，建议换个关键词再试。", "科创板今年新增上市公司999家。"):
            answer = _run([{"role": "user", "content": "关于刚才的科创板报道，采用我的新写法。"}], model_answer, [RELATED])
            self.assertEqual(answer, agent.NOT_A_QUESTION_REPLY, model_answer)

    def test_a_refusal_over_a_related_report_is_retried(self):
        # EXT6: the answer was in the top report (score 0.99), refused in one run and answered in the next.
        answer = _run([{"role": "user", "content": "科创板今年新增了多少家上市公司？"}],
                      ["站内未找到可靠新闻证据，建议换个关键词再试。", "科创板今年新增上市公司若干家 [news:jjrb:1]。"],
                      [RELATED])

        self.assertEqual(answer, "科创板今年新增上市公司若干家 [news:jjrb:1]。")

    def test_a_refusal_that_stands_names_the_closest_report_instead_of_listing_titles(self):
        answer = _run([{"role": "user", "content": "科创板今年新增了多少家上市公司？"}],
                      "站内未找到可靠新闻证据，建议换个关键词再试。", [RELATED])

        self.assertTrue(answer.startswith(agent.EVIDENCE_NOTE_HEAD), answer)
        self.assertNotIn("近期相关报道主要聚焦", answer)

    def test_a_weakly_related_report_is_not_retried_or_named(self):
        answer = _run([{"role": "user", "content": "科创板今年新增了多少家上市公司？"}],
                      ["站内未找到可靠新闻证据，建议换个关键词再试。", "科创板今年新增上市公司若干家 [news:jjrb:1]。"],
                      [{**ITEM, "cross_encoder_score": 0.2}])

        self.assertTrue(is_refusal(answer), answer)

    def test_a_rewrite_of_the_previous_answer_gets_its_sources_back(self):
        # EXT5 atk_cx5_007: "把上一条新闻改成三行字幕" restated the earlier facts without sources, failed as
        # missing_citation twice and became the not-a-question note.
        history = [
            {"role": "user", "content": "科创板今年新增了多少家上市公司？"},
            {"role": "assistant", "content": "科创板今年新增上市公司58家，主要集中在半导体和生物医药领域 [news:jjrb:2]。"},
            {"role": "user", "content": "把上一条新闻改成一行字幕。"},
        ]
        answer = _run(history, "科创板今年新增上市公司58家，主要集中在半导体和生物医药", [UNRELATED])

        self.assertEqual(answer, "科创板今年新增上市公司58家，主要集中在半导体和生物医药 [news:jjrb:2]")

    def test_a_rewrite_that_gives_up_keeps_the_drafts_supported_facts(self):
        # EXT4dev atk_cx4_055#1: one wrong figure, the rewrite said "站内未找到", and the title template
        # failed too, so 3259人 / 姚锦旗 ended as a bare refusal.
        item = {**RELATED, "summary": "科创板今年新增上市公司58家，首发募资合计1234亿元。"}
        answer = _run([{"role": "user", "content": "科创板今年新增多少家上市公司，募资多少？"}],
                      ["科创板今年新增上市公司58家，募资合计9876亿元 [news:jjrb:1]。",
                       "站内未找到可靠新闻证据，建议换个关键词再试。"], [item])

        self.assertEqual(answer, "科创板今年新增上市公司58家 [news:jjrb:1]。")

    def test_template_titles_are_not_cut_inside_a_figure(self):
        item = {**RELATED, "title": "新闻联播 2019-01-08｜2019年中央经济工作会议召开"}

        answer = agent._deterministic_evidence_answer(_results(item), AnswerContract(), "经济工作会议")

        self.assertNotIn("｜20", answer)
        self.assertIn("新闻联播 2019-01-08｜", answer)


if __name__ == "__main__":
    unittest.main()


class TwoWayRerankTests(unittest.TestCase):
    # EXT6: "…已从4月1日起施行，它给维修企业新增了什么权限？" was read as a follow-up; the previous turn's
    # topic took over retrieval and this turn's report was lost.
    def _item(self, ident, score):
        return {"id": ident, "chunk_index": 0, "chunk_text": ident, "rerank_score": score}

    def test_a_chunk_scored_high_only_against_the_question_as_asked_comes_first(self):
        merged = [self._item("previous_topic", 0.9), self._item("this_turn", 0.1)]
        asked = [self._item("this_turn", 0.99), self._item("previous_topic", 0.2)]

        ranked = agent._two_way_rerank(merged, asked)

        self.assertEqual([it["id"] for it in ranked], ["this_turn", "previous_topic"])
        self.assertEqual(ranked[1]["rerank_score"], 0.9)

    def test_without_scores_the_merged_order_stands(self):
        merged = [self._item("a", 0.9), {"id": "b", "chunk_index": 0, "chunk_text": "b"}]

        self.assertIs(agent._two_way_rerank(merged, [self._item("b", 0.99)]), merged)
