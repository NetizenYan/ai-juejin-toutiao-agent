import unittest

from scripts.sync_pg_metadata_from_qdrant import (
    chunk_row_from_point,
    parent_row_from_payload,
)


class SyncPgMetadataFromQdrantTests(unittest.TestCase):
    def test_parent_row_uses_evidence_and_summary_content(self):
        payload = {
            "doc_id": "jjrb:abc",
            "source": "jjrb",
            "source_doc_id": "abc",
            "title": "测试标题",
            "publish_time": "2026-06-23 00:00:00",
            "publish_ts": 1782140400,
            "section": "要闻",
            "category": "财经/经济",
            "url": "https://example.test/news",
            "evidence_id": "news:jjrb:abc",
            "summary": "这是一段父文档摘要。",
            "chunk_text": "短片段",
        }

        row = parent_row_from_payload(payload)

        self.assertEqual(row["evidence_id"], "news:jjrb:abc")
        self.assertEqual(row["source_code"], "jjrb")
        self.assertEqual(row["content"], "这是一段父文档摘要。")
        self.assertEqual(row["content_length"], len("这是一段父文档摘要。"))

    def test_chunk_row_prefixes_collection_to_avoid_cross_collection_collisions(self):
        payload = {
            "evidence_id": "news:jjrb:abc",
            "chunk_type": "body",
            "chunk_index": 2,
            "chunk_text": "片段内容",
            "api_embedding_model": "Pro/BAAI/bge-m3",
        }

        row = chunk_row_from_point(
            point_id=12345,
            payload=payload,
            collection="news_chunks_v32e_api_bge_m3_test",
            vector_model="fallback-model",
            vector_dim=1024,
        )

        self.assertEqual(
            row["chunk_id"],
            "news_chunks_v32e_api_bge_m3_test|news:jjrb:abc|body|2|12345",
        )
        self.assertEqual(row["collection_name"], "news_chunks_v32e_api_bge_m3_test")
        self.assertEqual(row["vector_model"], "Pro/BAAI/bge-m3")
        self.assertEqual(row["qdrant_point_id"], 12345)


if __name__ == "__main__":
    unittest.main()
