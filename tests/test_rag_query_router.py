import unittest

from harness.rag_query_router import is_econ_finance_query, route_rag_query


class RagQueryRouterTests(unittest.TestCase):
    def test_title_or_entity_query_keeps_summary_first(self):
        route = route_rag_query("OpenAI GPT-5")

        self.assertEqual(route.to_dict(), {
            "query_type": "title_or_entity",
            "retrieval_strategy": "summary_first",
            "body_fallback_slots": 0,
            "reason": "no detail/timeline/source trigger matched",
        })

    def test_content_detail_query_enables_one_body_fallback_slot(self):
        route = route_rag_query("这条新闻具体内容说了什么")

        self.assertEqual(route.query_type, "content_detail")
        self.assertEqual(route.retrieval_strategy, "summary_with_body_fallback")
        self.assertEqual(route.body_fallback_slots, 1)
        self.assertEqual(route.reason, "matched content-detail trigger")

    def test_timeline_query_takes_priority_over_content_detail(self):
        route = route_rag_query("人工智能最近有什么进展")

        self.assertEqual(route.query_type, "timeline_or_recent")
        self.assertEqual(route.retrieval_strategy, "time_aware_hybrid")
        self.assertEqual(route.body_fallback_slots, 1)
        self.assertEqual(route.reason, "matched timeline/recent trigger")

    def test_near_term_query_uses_time_aware_route(self):
        route = route_rag_query("近期外贸进出口有什么新情况")

        self.assertEqual(route.query_type, "timeline_or_recent")
        self.assertEqual(route.retrieval_strategy, "time_aware_hybrid")
        self.assertEqual(route.body_fallback_slots, 1)

    def test_econ_finance_query_detection(self):
        self.assertTrue(is_econ_finance_query("最近财经和金融市场有什么新闻"))
        self.assertTrue(is_econ_finance_query("近期外贸进出口有什么新情况"))
        self.assertTrue(is_econ_finance_query("最近高质量发展和新质生产力有什么新闻"))
        self.assertTrue(is_econ_finance_query("现代化产业体系和新动能有什么进展"))
        self.assertTrue(is_econ_finance_query("最近有没有关于宏观政策银河补贴行动的新闻"))
        self.assertTrue(is_econ_finance_query("科技创新和产业升级有什么关系"))
        self.assertFalse(is_econ_finance_query("今天有什么体育新闻"))

    def test_source_constrained_query_takes_highest_priority(self):
        route = route_rag_query("新闻联播最近提到人工智能了吗")

        self.assertEqual(route.query_type, "source_constrained")
        self.assertEqual(route.retrieval_strategy, "hybrid_with_source_filter")
        self.assertEqual(route.body_fallback_slots, 1)
        self.assertEqual(route.reason, "matched source trigger")

    def test_disabled_router_returns_configured_safe_default(self):
        route = route_rag_query("最新进展是什么", enabled=False, default_body_fallback_slots=0)

        self.assertEqual(route.query_type, "title_or_entity")
        self.assertEqual(route.retrieval_strategy, "summary_first")
        self.assertEqual(route.body_fallback_slots, 0)
        self.assertEqual(route.reason, "query router disabled")


if __name__ == "__main__":
    unittest.main()
