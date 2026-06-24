import unittest

from harness.query_understanding import understand_user_query


class QueryUnderstandingTests(unittest.TestCase):
    def test_extracts_brief_plain_language_constraints(self):
        understanding = understand_user_query("最近高质量发展有什么新闻？简单说说，保留引用")

        self.assertEqual(understanding.style, "plain_language")
        self.assertEqual(understanding.detail_level, "brief")
        self.assertTrue(understanding.must_include_citations)
        self.assertEqual(understanding.time_scope, "recent")

    def test_extracts_detail_constraint(self):
        understanding = understand_user_query("请详细分析新质生产力相关报道")

        self.assertEqual(understanding.detail_level, "detail")

    def test_extracts_max_chars_and_points(self):
        understanding = understand_user_query("请用不超过120字回答，列三点，并带新闻证据")

        self.assertEqual(understanding.max_chars, 120)
        self.assertEqual(understanding.max_points, 3)
        self.assertTrue(understanding.must_include_citations)

    def test_extracts_chinese_number_points_and_time_scope(self):
        understanding = understand_user_query("本周经济新闻两点说明，100字以内")

        self.assertEqual(understanding.max_points, 2)
        self.assertEqual(understanding.max_chars, 100)
        self.assertEqual(understanding.time_scope, "this_week")


if __name__ == "__main__":
    unittest.main()
