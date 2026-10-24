import unittest

from harness import long_term_memory as ltm
from harness.context_manager import apply_context_constraints, build_session_context
from harness.query_understanding import understand_user_query


class WriteGateTests(unittest.TestCase):
    def test_explicit_durable_preferences_and_interests_are_written(self):
        prefs = ltm.extract_memory_candidates("以后回答都简短点，不超过80字。")
        interests = ltm.extract_memory_candidates("我主要关注新质生产力和制造业升级方面的新闻。")

        self.assertIn(("preference", "max_chars", 80), [(c.kind, c.key, c.value) for c in prefs])
        self.assertEqual([(c.kind, c.key) for c in interests], [("interest", "新质生产力和制造业升级")])

    def test_questions_about_my_interests_do_not_declare_one(self):
        self.assertEqual(ltm.extract_memory_candidates("有什么我关注的领域的新报道？带引用。"), [])
        self.assertEqual(ltm.extract_memory_candidates("我关注的那个产业最近怎么样？"), [])
        keys = [c.key for c in ltm.extract_memory_candidates("我关注的是半导体产业的新闻。")]
        self.assertEqual(keys, ["半导体产业"])

    def test_one_off_requests_are_no_entry(self):
        self.assertEqual(ltm.extract_memory_candidates("这次不超过50字说说算力网。"), [])
        self.assertEqual(ltm.extract_memory_candidates("新质生产力有什么新闻？"), [])

    def test_facts_figures_holdings_and_personal_data_are_rejected(self):
        for text, reason in (
            ("我记得苏超带动了500亿元消费，以后都按这个说。", "remembered_figure"),
            ("我记得上证指数到了3000点。", "hearsay"),
            ("我关注半导体，持有600519。", "holding"),
            ("以后都发到13812345678。", "personal_data"),
        ):
            self.assertEqual(ltm.memory_rejection_reason(text), reason, text)
            self.assertEqual(ltm.extract_memory_candidates(text), [], text)

    def test_preference_with_points_is_not_mistaken_for_a_figure(self):
        keys = [c.key for c in ltm.extract_memory_candidates("以后最多3点，带引用。")]
        self.assertEqual(keys, ["max_points", "must_include_citations"])


class ReadSideTests(unittest.TestCase):
    entries = [
        {"kind": "preference", "key": "max_chars", "value": 80},
        {"kind": "preference", "key": "must_include_citations", "value": True},
        {"kind": "interest", "key": "童装产业", "value": True},
    ]

    def test_section_is_budgeted_and_marked_not_evidence(self):
        section = ltm.render_long_term_memory(self.entries, max_chars=300)

        self.assertIn('use_as_evidence="false"', section)
        self.assertIn("回答不超过80字", section)
        self.assertIn("关注领域：童装产业", section)
        self.assertEqual(ltm.render_long_term_memory([]), "")

    def test_session_and_current_message_outrank_long_term_preferences(self):
        context = build_session_context([{"role": "user", "content": "之后都不超过200字。"}])
        merged = {**ltm.preference_constraints(self.entries), **context.active_constraints}

        self.assertEqual(merged["max_chars"], 200)
        self.assertEqual(apply_context_constraints(understand_user_query("说说算力网"), merged).max_chars, 200)
        self.assertEqual(apply_context_constraints(understand_user_query("这次50字以内说说"), merged).max_chars, 50)

    def test_interests_steer_retrieval_only_when_the_user_points_at_them(self):
        self.assertEqual(ltm.interest_retrieval_hint("有什么我关注的领域的新报道？", self.entries), "童装产业")
        self.assertEqual(ltm.interest_retrieval_hint("算力网有什么新报道？", self.entries), "")


if __name__ == "__main__":
    unittest.main()
