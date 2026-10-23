import asyncio
import unittest
from types import SimpleNamespace

from config.vector_conf import FILTER_PAYLOAD_FIELDS, ensure_payload_indexes


class _FakeQdrant:
    def __init__(self, existing):
        self.schema = {name: object() for name in existing}
        self.created = []

    async def get_collection(self, _collection):
        return SimpleNamespace(payload_schema=dict(self.schema))

    async def create_payload_index(self, collection, field_name, field_schema, wait):
        self.created.append((collection, field_name, str(field_schema), wait))
        self.schema[field_name] = object()


class PayloadIndexTests(unittest.TestCase):
    def test_filter_fields_cover_rag_filters(self):
        # rag_search filters chunk_type (every query), source (source-limited) and evidence_id (carry-over)
        self.assertEqual(set(FILTER_PAYLOAD_FIELDS), {"chunk_type", "source", "evidence_id"})

    def test_creates_only_missing_indexes_and_waits(self):
        client = _FakeQdrant(existing={"source"})
        created = asyncio.run(ensure_payload_indexes(client, "c"))
        self.assertEqual(created, ["chunk_type", "evidence_id", "publish_ts"])
        self.assertIn("integer", client.created[-1][2].lower())
        self.assertTrue(all(wait for *_rest, wait in client.created))
        self.assertEqual(asyncio.run(ensure_payload_indexes(client, "c")), [])


if __name__ == "__main__":
    unittest.main()
