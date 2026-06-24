"""Report basic coverage for the unified Qdrant chunk collection."""

from __future__ import annotations

import asyncio
import json
from collections import Counter

from config.vector_conf import CHUNK_COLLECTION, get_qdrant, load_meta


async def collect_coverage() -> dict:
    qdrant = get_qdrant()
    total = await qdrant.count(collection_name=CHUNK_COLLECTION, exact=True)
    offset = None
    parent_ids: set[int] = set()
    chunk_types: Counter[str] = Counter()
    source_count = 0

    while True:
        points, offset = await qdrant.scroll(
            collection_name=CHUNK_COLLECTION,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            parent_id = payload.get("parent_news_id") or payload.get("news_id") or payload.get("id")
            try:
                parent_ids.add(int(parent_id))
            except (TypeError, ValueError):
                pass
            chunk_types[str(payload.get("chunk_type") or "unknown")] += 1
            if payload.get("source") or payload.get("author"):
                source_count += 1
        if offset is None:
            break

    return {
        "collection_name": CHUNK_COLLECTION,
        "point_count": int(total.count),
        "parent_count": len(parent_ids),
        "chunk_type_counts": dict(chunk_types),
        "points_with_source": source_count,
        "rag_meta": load_meta(),
    }


async def main() -> None:
    print(json.dumps(await collect_coverage(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
