import unittest

from eval import answer_quality as aq


class AnswerQualityTests(unittest.TestCase):
    def test_packets_carry_cited_evidence_and_template_flag(self):
        rows = [{
            "id": "c1",
            "case_type": "A_exact_news_qa",
            "question": "新质生产力有什么新闻？",
            "answer": "近期相关报道主要聚焦新质生产力。[news:jjrb:001]",
            "done": {"validationTrace": [{"stage": "initial"}, {"stage": "rewrite_1"}]},
        }]
        evidence = {"news:jjrb:001": {"title": "标题", "date": "2026-05-01", "source": "jjrb", "text": "正文"}}

        packet = aq.build_packets(rows, evidence)[0]

        self.assertTrue(packet["is_template"])
        self.assertEqual(packet["cited"][0]["title"], "标题")
        self.assertEqual(packet["trace_stages"], ["initial", "rewrite_1"])
        self.assertIn("[news:jjrb:001]", aq.judge_prompt(packet))

    def test_parse_judgment_rejects_out_of_range_scores(self):
        good = '{"relevance":2,"faithfulness":1,"completeness":1,"constraints":2,"usefulness":4,"flags":["template","x"]}'
        self.assertEqual(aq.parse_judgment("评分：" + good)["flags"], ["template"])
        self.assertIsNone(aq.parse_judgment('{"relevance":3,"faithfulness":1,"completeness":1,"constraints":2,"usefulness":4}'))
        self.assertIsNone(aq.parse_judgment("no json"))

    def test_summary_splits_template_and_non_template(self):
        packets = [
            {"id": "a", "case_type": "A", "is_template": True},
            {"id": "b", "case_type": "A", "is_template": False},
        ]
        scores = [
            {"id": "a", "relevance": 1, "faithfulness": 2, "completeness": 0, "constraints": 2, "usefulness": 2, "flags": ["template"], "grader": "g"},
            {"id": "b", "relevance": 2, "faithfulness": 2, "completeness": 2, "constraints": 2, "usefulness": 5, "flags": [], "grader": "g"},
        ]

        summary = aq.summarize(packets, scores)

        self.assertEqual(summary["template"]["usefulness"], 2)
        self.assertEqual(summary["non_template"]["useful_rate"], 1.0)
        self.assertEqual(summary["overall"]["flags"], {"template": 1})
        self.assertIn("| 模板兜底 | 1 |", aq.render_markdown(summary))

    def test_long_transcript_window_follows_the_answer(self):
        transcript = "甲" * 2000 + "市场监管总局介绍市场监管如何支撑高质量发展" + "乙" * 2000

        window = aq.best_window(transcript, "市场监管总局介绍了如何支撑高质量发展", size=100)

        self.assertIn("市场监管总局", window)

    def test_agreement_reports_kappa_and_large_disagreements(self):
        a = [{"id": "x", "usefulness": 5, **dict.fromkeys(aq.DIMENSIONS, 2)},
             {"id": "y", "usefulness": 1, **dict.fromkeys(aq.DIMENSIONS, 1)}]
        b = [{"id": "x", "usefulness": 4, **dict.fromkeys(aq.DIMENSIONS, 2)},
             {"id": "y", "usefulness": 4, **dict.fromkeys(aq.DIMENSIONS, 2)}]

        result = aq.agreement(a, b)

        self.assertEqual(result["n"], 2)
        self.assertEqual(result["usefulness_within_1"], 0.5)
        self.assertEqual([d["id"] for d in result["large_disagreements"]], ["y"])


if __name__ == "__main__":
    unittest.main()
