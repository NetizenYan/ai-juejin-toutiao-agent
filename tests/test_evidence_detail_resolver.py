import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness.evidence_detail_resolver import normalize_evidence_id, resolve_evidence_detail


class _FakeQdrant:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def scroll(self, **kwargs):
        condition = kwargs["scroll_filter"].must[0]
        value = getattr(condition.match, "value", None)
        self.calls.append((kwargs["collection_name"], condition.key, value))
        payload = self.responses.get((condition.key, value))
        if payload is None:
            return [], None
        return [SimpleNamespace(payload=payload)], None


class EvidenceDetailResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_ai_router_exposes_evidence_detail_endpoint(self):
        from routers.ai import router

        paths = {route.path for route in router.routes}
        self.assertIn("/api/ai/evidence-detail", paths)

    def test_normalizes_bracketed_evidence_ids_without_losing_source_scope(self):
        self.assertEqual(
            normalize_evidence_id("[news:jjrb:8dcc9e6349959132]"),
            "news:jjrb:8dcc9e6349959132",
        )
        self.assertEqual(normalize_evidence_id("news:2726"), "news:2726")
        self.assertEqual(
            normalize_evidence_id("[news:cctv-20200101-3]"),
            "news:cctv-20200101-3",
        )

    async def test_resolves_jjrb_evidence_from_qdrant_payload_without_integer_cast(self):
        payload = {
            "evidence_id": "news:jjrb:8dcc9e6349959132",
            "parent_news_id": "jjrb:8dcc9e6349959132",
            "news_id": "jjrb:8dcc9e6349959132",
            "source": "jjrb",
            "title": "高质量发展取得新进展",
            "publish_time": "2026-06-10 00:00:00",
            "chunk_text": "经济日报报道，高质量发展和新质生产力相关政策持续推进。",
            "text": "经济日报报道，高质量发展和新质生产力相关政策持续推进。",
            "chunk_index": 0,
        }
        fake_qdrant = _FakeQdrant({("evidence_id", "news:jjrb:8dcc9e6349959132"): payload})

        result = await resolve_evidence_detail(
            "[news:jjrb:8dcc9e6349959132]",
            qdrant_factory=lambda: fake_qdrant,
            collections=["toutiao_econ_chunks_candidate_20260621"],
            jsonl_paths=[],
        )

        self.assertTrue(result["found"])
        self.assertEqual(result["evidence_id"], "news:jjrb:8dcc9e6349959132")
        self.assertEqual(result["source"], "经济日报")
        self.assertEqual(result["title"], "高质量发展取得新进展")
        self.assertEqual(result["parent_id"], "jjrb:8dcc9e6349959132")
        self.assertEqual(result["chunk_index"], 0)
        self.assertEqual(result["collection"], "toutiao_econ_chunks_candidate_20260621")
        self.assertIn("高质量发展", result["snippet"])
        self.assertIn("新质生产力", result["content_excerpt"])
        self.assertNotIn(("toutiao_econ_chunks_candidate_20260621", "news_id", 8), fake_qdrant.calls)

    async def test_resolves_numeric_news_id_from_qdrant_payload(self):
        payload = {
            "news_id": 2726,
            "parent_news_id": 2726,
            "source": "新闻联播",
            "title": "站内新闻样例",
            "publish_time": "2026-06-01 12:00:00",
            "summary": "这是站内新闻摘要。",
            "chunk_text": "这是站内新闻片段。",
        }
        fake_qdrant = _FakeQdrant({("news_id", 2726): payload})

        result = await resolve_evidence_detail(
            "[news:2726]",
            qdrant_factory=lambda: fake_qdrant,
            collections=["toutiao_chunks_claude"],
            jsonl_paths=[],
        )

        self.assertTrue(result["found"])
        self.assertEqual(result["evidence_id"], "news:2726")
        self.assertEqual(result["parent_id"], 2726)
        self.assertEqual(result["title"], "站内新闻样例")

    async def test_falls_back_to_jsonl_parent_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "econ.jsonl"
            jsonl_path.write_text(
                json.dumps(
                    {
                        "doc_id": "jjrb:abc123",
                        "source": "jjrb",
                        "title": "经济日报父文档",
                        "content": "这是父文档正文，可以用于详情展示。" * 20,
                        "publish_time": "2026-06-07 00:00:00",
                        "section": "财金",
                        "url": "https://example.invalid/news",
                        "evidence_id": "news:jjrb:abc123",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            fake_qdrant = _FakeQdrant()

            result = await resolve_evidence_detail(
                "news:jjrb:abc123",
                qdrant_factory=lambda: fake_qdrant,
                collections=["missing_collection"],
                jsonl_paths=[jsonl_path],
            )

        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "经济日报")
        self.assertEqual(result["title"], "经济日报父文档")
        self.assertEqual(result["parent_id"], "jjrb:abc123")
        self.assertIn("父文档正文", result["content_excerpt"])
        self.assertTrue(result["detail_available"])

    async def test_returns_not_found_without_fabricating_detail(self):
        result = await resolve_evidence_detail(
            "news:jjrb:unknown",
            qdrant_factory=lambda: _FakeQdrant(),
            collections=["toutiao_econ_chunks_candidate_20260621"],
            jsonl_paths=[],
        )

        self.assertFalse(result["found"])
        self.assertEqual(result["evidence_id"], "news:jjrb:unknown")
        self.assertEqual(result["error"], "evidence_not_found")
        self.assertNotIn("title", result)

    async def test_jsonl_fallback_does_not_match_unrelated_row(self):
        # Regression: a non-empty JSONL must not satisfy an unknown evidence_id.
        # Previously _row_matches mixed query-derived ids into the row-id set and
        # tested membership against itself, so any id matched the first line.
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "econ.jsonl"
            jsonl_path.write_text(
                json.dumps(
                    {
                        "doc_id": "jjrb:realdoc",
                        "source_doc_id": "realdoc",
                        "source": "jjrb",
                        "title": "真实存在的经济日报文档",
                        "content": "正文片段。" * 20,
                        "evidence_id": "news:jjrb:realdoc",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = await resolve_evidence_detail(
                "news:jjrb:doesnotexist",
                qdrant_factory=lambda: _FakeQdrant(),
                collections=["missing_collection"],
                jsonl_paths=[jsonl_path],
            )

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "evidence_not_found")
        self.assertNotIn("title", result)


if __name__ == "__main__":
    unittest.main()
