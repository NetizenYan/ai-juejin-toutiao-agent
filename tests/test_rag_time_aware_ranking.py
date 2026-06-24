import unittest
from datetime import datetime
from types import SimpleNamespace

from harness.rag_ranking import infer_publish_ts, quality_score, time_aware_hybrid_rerank
from harness import rag_search
from harness.rag_search import search_news_rag


class _FakeEmbeddingClient:
    class embeddings:
        @staticmethod
        async def create(model, input):  # noqa: ANN001
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


class _FakeQdrant:
    def __init__(self, points):
        self.points = points
        self.collections = []
        self.query_kwargs = []

    async def query_points(self, **_kwargs):
        self.collections.append(_kwargs.get("collection_name"))
        self.query_kwargs.append(_kwargs)
        return SimpleNamespace(points=self.points)

    async def scroll(self, **_kwargs):
        return [], None


def _point(score, payload):
    return SimpleNamespace(score=score, payload=payload)


class RagTimeAwareRankingTests(unittest.IsolatedAsyncioTestCase):
    def test_infers_legacy_news_date_from_title(self):
        ts = infer_publish_ts({"title": "新闻联播 2009-05-09｜近期装备制造等行业出现回稳态势"})

        self.assertEqual(datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "2009-05-09")

    def test_time_aware_rerank_promotes_recent_news_over_old_high_vector_match(self):
        old_item = {
            "title": "新闻联播 2009-05-09｜近期装备制造等行业出现回稳态势",
            "summary": "经济数据有所变化",
            "score": 0.99,
        }
        recent_item = {
            "title": "经济向新向优发展稳步推进",
            "summary": "5月份制造业和服务业数据体现经济运行情况",
            "publish_time": "2026-06-01 00:00:00",
            "score": 0.70,
        }

        ranked = time_aware_hybrid_rerank(
            "最近有什么经济新闻？",
            [old_item, recent_item],
            now_ts=datetime(2026, 6, 21).timestamp(),
        )

        self.assertEqual(ranked[0]["title"], "经济向新向优发展稳步推进")
        self.assertGreater(ranked[0]["recency_score"], ranked[1]["recency_score"])

    def test_finance_clickbait_quality_is_low(self):
        item = {
            "title": "A股:周六上午传来3个特大级消息!A股或迎更大级别变盘行情？",
            "summary": "资本市场短线判断。",
        }

        self.assertLessEqual(quality_score(item), 0.35)

    def test_old_non_econ_source_quality_is_low(self):
        item = {
            "title": "欧洲足坛最新转会动态更新",
            "summary": "球队转会市场消息。",
            "source": "old",
        }

        self.assertLessEqual(quality_score(item), 0.35)

    def test_generic_news_title_quality_is_low(self):
        item = {
            "title": "图片新闻",
            "summary": "地方产业现场图片报道。",
            "source": "jjrb",
        }

        self.assertLessEqual(quality_score(item), 0.35)

    async def test_search_filters_severe_legacy_noise_when_alternatives_exist(self):
        points = [
            _point(0.99, {
                "news_id": 1,
                "title": "新闻联播 2009-11-23｜nannannannannannannannan",
                "chunk_text": "nannannannannannan",
                "source": "新闻联播",
            }),
            _point(0.72, {
                "news_id": 2,
                "title": "经济向新向优发展稳步推进",
                "chunk_text": "5月份制造业采购经理指数等数据体现经济运行情况。",
                "publish_time": "2026-06-01 00:00:00",
                "publish_ts": int(datetime(2026, 6, 1).timestamp()),
                "source": "经济日报",
            }),
            _point(0.70, {
                "news_id": 3,
                "title": "外贸新引擎彰显经济韧性活力",
                "chunk_text": "前4个月货物贸易进出口数据体现外贸韧性。",
                "publish_time": "2026-05-27 00:00:00",
                "publish_ts": int(datetime(2026, 5, 27).timestamp()),
                "source": "经济日报",
            }),
            _point(0.68, {
                "news_id": 4,
                "title": "银行理财打新热度上升",
                "chunk_text": "银行理财和金融市场近期出现新变化。",
                "publish_time": "2026-06-05 00:00:00",
                "publish_ts": int(datetime(2026, 6, 5).timestamp()),
                "source": "经济日报",
            }),
        ]

        result = await search_news_rag(
            "最近有什么经济新闻？",
            limit=3,
            embedding_client_factory=lambda: _FakeEmbeddingClient(),
            qdrant_factory=lambda: _FakeQdrant(points),
            assert_meta_matches_fn=lambda _model, _dim: None,
        )

        titles = [item["title"] for item in result["items"]]
        self.assertTrue(result["time_aware_ranking"])
        self.assertGreaterEqual(result["low_quality_filtered"], 1)
        self.assertNotIn("新闻联播 2009-11-23｜nannannannannannannannan", titles)
        self.assertIn("2026", result["items"][0]["publish_time"])
        self.assertGreater(quality_score(result["items"][0]), 0.2)

    async def test_recent_query_returns_empty_when_only_stale_candidates_exist(self):
        points = [
            _point(0.99, {
                "news_id": 11,
                "title": "新闻联播 2009-05-09｜近期装备制造等行业出现回稳态势",
                "chunk_text": "经济数据有所变化。",
                "source": "新闻联播",
            }),
            _point(0.92, {
                "news_id": 12,
                "title": "新闻联播 2012-11-20｜我国经济温度目前是冷是热",
                "chunk_text": "历史经济报道。",
                "source": "新闻联播",
            }),
        ]

        result = await search_news_rag(
            "最近有什么经济新闻？",
            limit=3,
            embedding_client_factory=lambda: _FakeEmbeddingClient(),
            qdrant_factory=lambda: _FakeQdrant(points),
            assert_meta_matches_fn=lambda _model, _dim: None,
        )

        self.assertTrue(result["time_aware_ranking"])
        self.assertGreaterEqual(result["stale_time_filtered"], 2)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["evidence_ids"], [])

    async def test_strict_recent_query_filters_year_old_candidates(self):
        points = [
            _point(0.99, {
                "news_id": 16,
                "title": "促进资本市场健康稳定发展",
                "chunk_text": "资本市场政策和投资者信心相关报道。",
                "publish_time": "2026-01-12 00:00:00",
                "publish_ts": int(datetime(2026, 1, 12).timestamp()),
                "source": "经济日报",
            }),
            _point(0.72, {
                "news_id": 17,
                "title": "持续稳定和增强资本市场信心",
                "chunk_text": "近期资本市场信心和政策预期改善。",
                "publish_time": "2026-05-22 00:00:00",
                "publish_ts": int(datetime(2026, 5, 22).timestamp()),
                "source": "经济日报",
            }),
            _point(0.70, {
                "news_id": 18,
                "title": "并购重组激发资本市场活力",
                "chunk_text": "资本市场改革工具持续落地。",
                "publish_time": "2026-06-02 00:00:00",
                "publish_ts": int(datetime(2026, 6, 2).timestamp()),
                "source": "经济日报",
            }),
        ]

        result = await search_news_rag(
            "最近资本市场有什么新闻？",
            limit=3,
            embedding_client_factory=lambda: _FakeEmbeddingClient(),
            qdrant_factory=lambda: _FakeQdrant(points),
            assert_meta_matches_fn=lambda _model, _dim: None,
        )

        titles = [item["title"] for item in result["items"]]
        self.assertGreaterEqual(result["stale_time_filtered"], 1)
        self.assertNotIn("促进资本市场健康稳定发展", titles)
        self.assertIn("持续稳定和增强资本市场信心", titles)

    async def test_recent_title_match_exempt_from_stale_filter(self):
        points = [
            _point(0.65, {
                "news_id": 30,
                "title": "新质生产力点燃高质量发展新引擎",
                "chunk_text": "新质生产力为高质量发展提供新动能。",
                "publish_time": "2026-01-15 00:00:00",
                "publish_ts": int(datetime(2026, 1, 15).timestamp()),
                "source": "经济日报",
            }),
            _point(0.72, {
                "news_id": 31,
                "title": "近期经济数据观察",
                "chunk_text": "5月份经济运行数据。",
                "publish_time": "2026-06-10 00:00:00",
                "publish_ts": int(datetime(2026, 6, 10).timestamp()),
                "source": "经济日报",
            }),
        ]

        result = await search_news_rag(
            "近期新质生产力点燃高质量发展新引擎有什么报道？",
            limit=3,
            embedding_client_factory=lambda: _FakeEmbeddingClient(),
            qdrant_factory=lambda: _FakeQdrant(points),
            assert_meta_matches_fn=lambda _model, _dim: None,
        )

        titles = [item["title"] for item in result["items"]]
        self.assertIn("新质生产力点燃高质量发展新引擎", titles)

    async def test_clickbait_old_item_is_filtered_when_better_recent_evidence_exists(self):
        points = [
            _point(0.99, {
                "news_id": 21,
                "title": "2026年消费降级，比想象更严重？4个明显现象，很多人躲不开了",
                "chunk_text": "消费市场变化。",
                "publish_time": "2026-06-20 11:25:20",
                "publish_ts": int(datetime(2026, 6, 20, 11, 25, 20).timestamp()),
                "source": "old",
            }),
            _point(0.72, {
                "news_id": 22,
                "title": "服务消费蓬勃发展",
                "chunk_text": "服务消费供给改善，市场活力释放。",
                "publish_time": "2026-05-11 00:00:00",
                "publish_ts": int(datetime(2026, 5, 11).timestamp()),
                "source": "经济日报",
            }),
            _point(0.70, {
                "news_id": 23,
                "title": "青春元气解锁市场新机",
                "chunk_text": "青年消费和创新供给带动消费市场新变化。",
                "publish_time": "2026-06-07 00:00:00",
                "publish_ts": int(datetime(2026, 6, 7).timestamp()),
                "source": "经济日报",
            }),
            _point(0.68, {
                "news_id": 24,
                "title": "解锁汽车后市场消费新动能",
                "chunk_text": "汽车后市场消费出现新动能。",
                "publish_time": "2026-05-19 00:00:00",
                "publish_ts": int(datetime(2026, 5, 19).timestamp()),
                "source": "经济日报",
            }),
            _point(0.66, {
                "news_id": 25,
                "title": "消费金融服务发力数字化革新",
                "chunk_text": "消费金融服务助力市场变化。",
                "publish_time": "2026-05-14 00:00:00",
                "publish_ts": int(datetime(2026, 5, 14).timestamp()),
                "source": "经济日报",
            }),
        ]

        result = await search_news_rag(
            "最近消费市场有什么变化？",
            limit=3,
            embedding_client_factory=lambda: _FakeEmbeddingClient(),
            qdrant_factory=lambda: _FakeQdrant(points),
            assert_meta_matches_fn=lambda _model, _dim: None,
        )

        titles = [item["title"] for item in result["items"]]
        self.assertGreaterEqual(result["low_quality_filtered"], 1)
        self.assertNotIn("2026年消费降级，比想象更严重？4个明显现象，很多人躲不开了", titles)
        self.assertIn("服务消费蓬勃发展", titles)

    async def test_econ_query_uses_configured_staging_collection_when_enabled(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": "econ:1",
                "title": "外贸新引擎彰显经济韧性活力",
                "chunk_text": "外贸进出口数据体现经济韧性。",
                "publish_time": "2026-05-27 00:00:00",
                "publish_ts": int(datetime(2026, 5, 27).timestamp()),
                "source": "经济日报",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            result = await search_news_rag(
                "近期外贸进出口有什么新情况？",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        self.assertEqual(result["collection_name"], "toutiao_exp_econ_recent_20260621")
        self.assertEqual(result["collection_route"], "econ_finance_query")
        self.assertTrue(fake.collections)
        self.assertTrue(all(name == "toutiao_exp_econ_recent_20260621" for name in fake.collections))

    async def test_policy_econ_query_uses_configured_staging_collection_when_enabled(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": "econ:policy:1",
                "title": "新质生产力加快培育高质量发展新动能",
                "chunk_text": "现代化产业体系建设和创新驱动政策推动经济高质量发展。",
                "publish_time": "2026-05-20 00:00:00",
                "publish_ts": int(datetime(2026, 5, 20).timestamp()),
                "source": "经济日报",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            result = await search_news_rag(
                "最近高质量发展和新质生产力有什么新闻？",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        self.assertEqual(result["collection_name"], "toutiao_exp_econ_recent_20260621")
        self.assertEqual(result["collection_route"], "econ_finance_query")
        self.assertTrue(fake.collections)
        self.assertTrue(all(name == "toutiao_exp_econ_recent_20260621" for name in fake.collections))

    async def test_source_alias_query_filters_econ_daily_source_code(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": "econ:source:1",
                "title": "多元理解经济发展成就",
                "chunk_text": "经济日报近期经济报道。",
                "publish_time": "2026-05-23 00:00:00",
                "publish_ts": int(datetime(2026, 5, 23).timestamp()),
                "source": "jjrb",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            result = await search_news_rag(
                "经济日报最近报道了哪些经济新闻？",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        self.assertEqual(result["collection_route"], "econ_finance_query")
        self.assertTrue(fake.query_kwargs)
        first_filter = fake.query_kwargs[0].get("query_filter")
        self.assertIsNotNone(first_filter)
        self.assertIn("jjrb", str(first_filter))

    async def test_multi_source_query_does_not_hard_filter_to_first_source(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": "econ:source:1",
                "title": "经济日报和人民日报综合报道",
                "chunk_text": "两类来源都可作为综合证据。",
                "publish_time": "2026-05-23 00:00:00",
                "publish_ts": int(datetime(2026, 5, 23).timestamp()),
                "source": "jjrb",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            await search_news_rag(
                "把经济日报和人民日报关于新质生产力的报道综合成两点。",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        first_filter = fake.query_kwargs[0].get("query_filter")
        self.assertNotIn("rmrb", str(first_filter))
        self.assertNotIn("jjrb", str(first_filter))

    async def test_news_broadcast_source_limited_query_keeps_default_collection(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": 62,
                "title": "新闻联播高质量发展报道",
                "chunk_text": "新闻联播报道高质量发展相关内容。",
                "publish_time": "2026-05-23 00:00:00",
                "publish_ts": int(datetime(2026, 5, 23).timestamp()),
                "source": "新闻联播",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            result = await search_news_rag(
                "只看新闻联播，最近高质量发展有什么报道？",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        self.assertEqual(result["collection_route"], "default")
        self.assertTrue(fake.collections)
        self.assertTrue(all(name == rag_search.CHUNK_COLLECTION for name in fake.collections))

    async def test_non_econ_query_keeps_default_collection_when_enabled(self):
        fake = _FakeQdrant([
            _point(0.72, {
                "news_id": 31,
                "title": "体育新闻",
                "chunk_text": "球队取得胜利。",
                "publish_time": "2026-06-01 00:00:00",
                "publish_ts": int(datetime(2026, 6, 1).timestamp()),
                "source": "站内新闻",
            }),
        ])
        original_settings = rag_search.settings
        rag_search.settings = SimpleNamespace(
            embedding_model="fake-embedding",
            rag_recall_limit=10,
            rag_ranking="hybrid",
            rag_chunk_type_filter="summary",
            rag_expand_body_evidence=False,
            rag_body_chunks_per_parent=1,
            rag_body_fallback_slots=0,
            rag_query_router_enabled=True,
            rag_econ_collection_enabled=True,
            rag_econ_collection_name="toutiao_exp_econ_recent_20260621",
            app_env="development",
        )
        try:
            result = await search_news_rag(
                "今天有什么体育新闻？",
                limit=3,
                embedding_client_factory=lambda: _FakeEmbeddingClient(),
                qdrant_factory=lambda: fake,
                assert_meta_matches_fn=lambda _model, _dim: None,
            )
        finally:
            rag_search.settings = original_settings

        self.assertEqual(result["collection_route"], "default")
        self.assertTrue(fake.collections)
        self.assertTrue(all(name == rag_search.CHUNK_COLLECTION for name in fake.collections))


if __name__ == "__main__":
    unittest.main()
