"""Add the payload indexes RAG filters need to existing Qdrant collections and rebuild their HNSW graph.

Collections built before config.vector_conf.ensure_payload_indexes existed have no payload index on
chunk_type, so filtered search (every RAG query filters chunk_type=summary) silently misses results.
Adding the index afterwards is not enough: Qdrant only builds filter-aware HNSW links during graph
construction, so this script also nudges hnsw ef_construct, which makes Qdrant rebuild the graph from
the stored vectors (no re-embedding).

Usage (project root):
    .venv/bin/python -m agent.scripts.ensure_qdrant_payload_indexes            # default RAG collections
    .venv/bin/python -m agent.scripts.ensure_qdrant_payload_indexes --collections a,b
"""
from __future__ import annotations

import argparse
import asyncio
import time

from qdrant_client.models import HnswConfigDiff

from agent.config.ai_conf import settings
from agent.config.vector_conf import (
    CHUNK_COLLECTION,
    COLLECTION,
    FILTER_PAYLOAD_FIELDS,
    ensure_payload_indexes,
    get_qdrant,
)


async def fix_collection(client, collection: str, *, force_rebuild: bool, timeout_s: int = 1800) -> dict:
    if not await client.collection_exists(collection):
        return {"collection": collection, "skipped": "not found"}
    created = await ensure_payload_indexes(client, collection)
    rebuilt = False
    # Only keyword filters run through HNSW; range fields are searched exactly.
    if any(field in FILTER_PAYLOAD_FIELDS for field in created) or force_rebuild:
        current = (await client.get_collection(collection)).config.hnsw_config.ef_construct
        await client.update_collection(collection, hnsw_config=HnswConfigDiff(ef_construct=128 if current != 128 else 129))
        rebuilt = True
        await asyncio.sleep(3)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if str((await client.get_collection(collection)).status).endswith("green"):
                break
            await asyncio.sleep(5)
    info = await client.get_collection(collection)
    return {"collection": collection, "created_indexes": created, "hnsw_rebuilt": rebuilt,
            "status": str(info.status), "payload_schema": sorted(info.payload_schema or {}),
            "points": info.points_count}


async def main(collections: list[str], force_rebuild: bool) -> None:
    client = get_qdrant()
    try:
        for collection in collections:
            print(await fix_collection(client, collection, force_rebuild=force_rebuild))
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--collections", default="",
                        help="comma-separated; default: econ, chunk and parent RAG collections")
    parser.add_argument("--force-rebuild", action="store_true", help="rebuild HNSW even if no index was missing")
    args = parser.parse_args()
    names = [c for c in args.collections.split(",") if c] or list(dict.fromkeys(
        [settings.rag_econ_collection_name, CHUNK_COLLECTION, COLLECTION]))
    asyncio.run(main(names, args.force_rebuild))
