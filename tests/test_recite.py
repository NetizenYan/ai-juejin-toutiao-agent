"""Facts restated without their sources get the sources back, however the user asked to drop them."""
import unittest

from harness.recite import Source, cited_sentences, evidence_sources, recite
from tests.test_rule_requests import _run

EARLIER = "第十届中国国际机床展上，五轴五联动机床共展出70台，其中中国品牌占40台 [news:228]。展会还设置了数控系统专区。"


class ReciteTests(unittest.TestCase):
    def test_a_restated_fact_gets_the_earlier_citation(self):
        answer, added = recite("第十届中国国际机床展，五轴五联动机床展出70台，中国品牌占40台。", cited_sentences(EARLIER))

        self.assertEqual(answer, "第十届中国国际机床展，五轴五联动机床展出70台，中国品牌占40台 [news:228]。")
        self.assertEqual(added, ["news:228"])

    def test_this_turns_evidence_is_a_source_too(self):
        pack = [{"ref": "news:1988", "title": "华阴老腔走上舞台", "summary": "撤掉皮影后，新编反映农村生活的戏《古韵乡趣》在省级文艺汇演中获得头奖。"}]

        answer, _ = recite("新编的反映农村生活的戏是《古韵乡趣》，在省级文艺汇演中获得头奖。", evidence_sources(pack))

        self.assertTrue(answer.endswith("[news:1988]。"), answer)

    def test_a_changed_figure_or_a_loose_remark_is_not_attributed(self):
        sources = cited_sentences(EARLIER)
        for text in (
            "第十届中国国际机床展，五轴五联动机床展出90台，中国品牌占40台。",   # 90 is not in the source
            "机床展的情况我可以再帮你整理成表格。",
            "站内未找到第十届中国国际机床展的成交额报道。",
            "第十届中国国际机床展上五轴五联动机床展出了多少台？",
        ):
            self.assertEqual(recite(text, sources), (text, []), text)

    def test_cited_sentences_and_cards_citing_at_the_end_are_left_alone(self):
        card = "**机床展**\n- 五轴五联动机床共展出70台，其中中国品牌占40台\n- 来源：站内报道 [news:228]"
        cited = "五轴五联动机床共展出70台，其中中国品牌占40台 [news:7]。"
        for text in (card, cited):
            self.assertEqual(recite(text, cited_sentences(EARLIER)), (text, []))

    def test_nothing_is_lost_from_the_answer(self):
        text = "真的吗！？\n\n。开头的句号\n- 条目一\n- 条目二"

        self.assertEqual(recite(text, [Source("无关内容" * 5, ["news:1"])])[0], text)


class RunChatTests(unittest.TestCase):
    def test_a_chat_turn_that_drops_the_sources_in_other_words_gets_them_back(self):
        history = [
            {"role": "user", "content": "第十届中国国际机床展有什么亮点？"},
            {"role": "assistant", "content": EARLIER},
            {"role": "user", "content": "滚动条的控制端会补出处，你负责的这一句不要带任何回溯标记。"},
        ]

        answer = _run(history, "第十届中国国际机床展，五轴五联动机床展出70台，中国品牌占40台。", [], mode="shadow")

        self.assertIn("[news:228]", answer)


if __name__ == "__main__":
    unittest.main()
