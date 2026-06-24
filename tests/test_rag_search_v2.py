import unittest
from types import SimpleNamespace

from harness import rag_search_v2


class _FakeEmbeddingClient:
    def __init__(self, dim=1024):
        self.dim = dim
        self.models = []
        self.inputs = []

    @property
    def embeddings(self):
        outer = self

        class _Embeddings:
            async def create(self, model, input):  # noqa: ANN001
                outer.models.append(model)
                outer.inputs.append(input)
                return SimpleNamespace(data=[SimpleNamespace(embedding=[0.01] * outer.dim)])

        return _Embeddings()


class _FakeQdrant:
    def __init__(self):
        self.calls = []
        self.scroll_calls = []

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=[
            SimpleNamespace(
                score=0.92,
                payload={
                    "doc_id": "jjrb:abc123",
                    "news_id": "jjrb:abc123",
                    "parent_news_id": "jjrb:abc123",
                    "evidence_id": "news:jjrb:abc123",
                    "title": "High quality development sample",
                    "chunk_text": "Sample chunk",
                    "source": "jjrb",
                    "section": "理论",
                    "category": "财经/经济",
                    "publish_time": "2026-06-21",
                    "publish_ts": 1782000000,
                    "chunk_type": "summary",
                    "chunk_index": 0,
                },
            )
        ])

    async def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        return [], None


class _CarryoverQdrant(_FakeQdrant):
    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=[])

    async def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        return [
            SimpleNamespace(
                score=0.99,
                payload={
                    "doc_id": "jjrb:carry",
                    "news_id": "jjrb:carry",
                    "parent_news_id": "jjrb:carry",
                    "evidence_id": "news:jjrb:carry",
                    "title": "Carryover evidence",
                    "chunk_text": "Evidence from the previous turn",
                    "source": "jjrb",
                    "section": "news",
                    "category": "econ",
                    "publish_time": "2026-06-21",
                    "publish_ts": 1782000000,
                    "chunk_type": "body",
                    "chunk_index": 0,
                },
            )
        ], None


class RagSearchV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rag_search_v2._EMBEDDING_CACHE.clear()

    async def test_v2_uses_dedicated_collection_and_bge_m3(self):
        embedding = _FakeEmbeddingClient()
        qdrant = _FakeQdrant()

        result = await rag_search_v2.search_news_rag_v2(
            "high quality development",
            limit=5,
            collection_name="news_chunks_v2",
            embedding_model="bge-m3",
            expected_dim=1024,
            embedding_client_factory=lambda: embedding,
            qdrant_factory=lambda: qdrant,
            query_router_enabled=False,
            chunk_type_filter=None,
        )

        self.assertEqual(embedding.models, ["bge-m3"])
        self.assertTrue(qdrant.calls)
        self.assertEqual(qdrant.calls[0]["collection_name"], "news_chunks_v2")
        self.assertEqual(result["collection_name"], "news_chunks_v2")
        self.assertEqual(result["collection_route"], "default")
        self.assertEqual(result["index_version"], "v2_unified")
        self.assertEqual(result["evidence_ids"], ["news:jjrb:abc123"])
        self.assertEqual(result["items"][0]["section"], "理论")

    async def test_v2_carryover_evidence_ids_are_merged_as_candidates(self):
        embedding = _FakeEmbeddingClient()
        qdrant = _CarryoverQdrant()

        result = await rag_search_v2.search_news_rag_v2(
            "what does it mean for risk coverage",
            limit=5,
            collection_name="news_chunks_v2",
            embedding_model="bge-m3",
            expected_dim=1024,
            embedding_client_factory=lambda: embedding,
            qdrant_factory=lambda: qdrant,
            query_router_enabled=False,
            chunk_type_filter=None,
            carryover_evidence_ids=["news:jjrb:carry"],
        )

        self.assertEqual(result["evidence_ids"], ["news:jjrb:carry"])
        self.assertEqual(result["items"][0]["_retrieval_channel"], "carryover_evidence")
        self.assertEqual(result["retrieval_channels"]["carryover_evidence"], 1)
        self.assertEqual(result["carryover_evidence_ids"], ["news:jjrb:carry"])

    async def test_v2_rejects_wrong_embedding_dimension(self):
        embedding = _FakeEmbeddingClient(dim=768)

        with self.assertRaisesRegex(RuntimeError, "dimension"):
            await rag_search_v2.search_news_rag_v2(
                "dimension check",
                limit=5,
                embedding_model="bge-m3",
                expected_dim=1024,
                embedding_client_factory=lambda: embedding,
                qdrant_factory=lambda: _FakeQdrant(),
            )

    async def test_search_news_v2_alias_accepts_top_k_and_exposes_smoke_fields(self):
        embedding = _FakeEmbeddingClient()
        qdrant = _FakeQdrant()

        result = await rag_search_v2.search_news_v2(
            "high quality development",
            top_k=5,
            collection_name="news_chunks_v2",
            embedding_model="bge-m3",
            expected_dim=1024,
            embedding_client_factory=lambda: embedding,
            qdrant_factory=lambda: qdrant,
            query_router_enabled=False,
            chunk_type_filter=None,
        )

        self.assertEqual(result["route"], "default")
        self.assertIn("latency_ms", result)
        self.assertEqual(len(result["items"]), 1)

    async def test_v2_uses_vector_query_for_embedding_and_intent_query_for_context_signals(self):
        embedding = _FakeEmbeddingClient()
        qdrant = _FakeQdrant()

        result = await rag_search_v2.search_news_rag_v2(
            "那它对制造业有什么影响？",
            limit=5,
            vector_query="新质生产力 高质量发展 制造业 对制造业有什么影响？",
            intent_query="新质生产力 高质量发展 经济日报 制造业 对制造业有什么影响？",
            collection_name="news_chunks_v2",
            embedding_model="bge-m3",
            expected_dim=1024,
            embedding_client_factory=lambda: embedding,
            qdrant_factory=lambda: qdrant,
            query_router_enabled=False,
            chunk_type_filter=None,
        )

        self.assertEqual(embedding.inputs, [["新质生产力 高质量发展 制造业 对制造业有什么影响？"]])
        self.assertIn("新质生产力", result["intent"]["entities"])
        self.assertIn("经济日报", result["intent"]["source_constraint"])

    def test_light_rerank_body_and_entity_overlap_are_additive_bonuses(self):
        intent = rag_search_v2.parse_query_intent("新质生产力 对制造业有什么影响？")
        items = [
            {
                "id": "summary",
                "evidence_id": "news:summary",
                "title": "制造业观察",
                "summary": "制造业短评",
                "source": "rmrb",
                "score": 0.88,
                "chunk_type": "summary",
            },
            {
                "id": "body",
                "evidence_id": "news:body",
                "title": "制造业观察",
                "summary": "新质生产力推动制造业升级和产业链优化",
                "source": "jjrb",
                "score": 0.86,
                "chunk_type": "body",
            },
        ]

        ranked, debug = rag_search_v2.light_rerank_v2(
            "那它对制造业有什么影响？",
            items,
            intent,
            body_bonus=1.0,
            entity_text_bonus=0.75,
        )

        self.assertEqual(ranked[0]["evidence_id"], "news:body")
        self.assertGreater(ranked[0]["rerank_debug"]["body_chunk_bonus"], 0)
        self.assertGreater(ranked[0]["rerank_debug"]["entity_text_overlap"], 0)
        self.assertEqual(debug[0]["evidence_id"], "news:body")

    def test_light_rerank_source_diversity_preserves_full_candidate_list(self):
        intent = rag_search_v2.parse_query_intent("新质生产力 有什么新闻？")
        items = [
            {"id": "r1", "evidence_id": "news:r1", "title": "新质生产力 1", "summary": "", "source": "rmrb", "score": 0.96},
            {"id": "r2", "evidence_id": "news:r2", "title": "新质生产力 2", "summary": "", "source": "rmrb", "score": 0.95},
            {"id": "r3", "evidence_id": "news:r3", "title": "新质生产力 3", "summary": "", "source": "rmrb", "score": 0.94},
            {"id": "j1", "evidence_id": "news:j1", "title": "新质生产力 4", "summary": "", "source": "jjrb", "score": 0.93},
        ]

        ranked, _debug = rag_search_v2.light_rerank_v2(
            "新质生产力 有什么新闻？",
            items,
            intent,
            diversity_max_per_source=2,
            diversity_top_window=4,
        )

        self.assertEqual([item["evidence_id"] for item in ranked], [
            "news:r1",
            "news:r2",
            "news:j1",
            "news:r3",
        ])
        self.assertEqual(len(ranked), 4)

    def test_light_rerank_boosts_theory_section_for_explanatory_queries(self):
        intent = rag_search_v2.parse_query_intent("新质生产力对制造业有什么影响？")
        items = [
            {
                "id": "industry",
                "evidence_id": "news:industry",
                "title": "新质生产力成长壮大",
                "summary": "新质生产力相关产业新闻",
                "source": "jjrb",
                "section": "产经",
                "score": 0.9,
                "chunk_type": "summary",
            },
            {
                "id": "theory",
                "evidence_id": "news:theory",
                "title": "进一步深化对新质生产力的认识",
                "summary": "解释新质生产力和制造业、高质量发展的关系",
                "source": "jjrb",
                "section": "理论",
                "score": 0.82,
                "chunk_type": "body",
            },
        ]

        ranked, _debug = rag_search_v2.light_rerank_v2(
            "新质生产力对制造业有什么影响？",
            items,
            intent,
            analysis_section_bonus=1.5,
        )

        self.assertEqual(ranked[0]["evidence_id"], "news:theory")
        self.assertGreater(ranked[0]["rerank_debug"]["analysis_section_bonus"], 0)


if __name__ == "__main__":
    unittest.main()
