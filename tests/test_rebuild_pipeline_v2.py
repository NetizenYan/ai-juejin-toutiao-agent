import json
import tempfile
import unittest
from pathlib import Path

from scripts import rebuild_pipeline


class RebuildPipelineV2Tests(unittest.TestCase):
    def test_estimate_dataset_uses_v2_defaults_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset = Path(tmpdir) / "sample.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "doc_id": "jjrb:sample",
                        "source": "jjrb",
                        "source_doc_id": "sample",
                        "title": "Sample policy economy news",
                        "content": "This is a short manually crafted sample content for local tests.",
                        "publish_time": "2026-06-21",
                        "publish_ts": 1782000000,
                        "evidence_id": "news:jjrb:sample",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = rebuild_pipeline.estimate_dataset(
                dataset,
                max_docs=None,
                collection=rebuild_pipeline.DEFAULT_COLLECTION,
                embedding_model=rebuild_pipeline.DEFAULT_EMBEDDING_MODEL,
                vector_dim=rebuild_pipeline.DEFAULT_VECTOR_DIM,
                body_size=600,
                body_overlap=120,
                max_body_chunks=8,
            )

        self.assertEqual(report["collection"], rebuild_pipeline.DEFAULT_COLLECTION)
        self.assertEqual(report["embedding_model"], rebuild_pipeline.DEFAULT_EMBEDDING_MODEL)
        self.assertEqual(report["vector_dim"], rebuild_pipeline.DEFAULT_VECTOR_DIM)
        self.assertEqual(report["docs"], 1)
        self.assertGreaterEqual(report["estimated_points"], 2)

    def test_parent_and_chunk_rows_keep_scoped_evidence_id(self):
        doc = {
            "doc_id": "jjrb:abc123",
            "source": "jjrb",
            "source_doc_id": "abc123",
            "title": "Scoped id sample",
            "content": "Scoped evidence content.",
            "publish_time": "2026-06-21",
            "publish_ts": 1782000000,
            "evidence_id": "news:jjrb:abc123",
        }

        parent = rebuild_pipeline.parent_row(doc)
        chunks = rebuild_pipeline.chunk_rows_for_doc(
            doc,
            collection="news_chunks_v2",
            embedding_model="bge-m3",
            vector_dim=1024,
            body_size=600,
            body_overlap=120,
            max_body_chunks=8,
        )

        self.assertEqual(parent["evidence_id"], "news:jjrb:abc123")
        self.assertTrue(all(row["evidence_id"] == "news:jjrb:abc123" for row in chunks))
        self.assertTrue(all(row["vector_model"] == "bge-m3" for row in chunks))
        self.assertTrue(all(row["vector_dim"] == 1024 for row in chunks))


if __name__ == "__main__":
    unittest.main()
