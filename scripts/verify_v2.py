"""Verify bge-m3 and the isolated Qdrant v2 collection."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.vector_conf import get_qdrant  # noqa: E402
from scripts.rebuild_pipeline import (  # noqa: E402
    DEFAULT_COLLECTION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_VECTOR_DIM,
    embed_texts,
    get_embedding_client,
)


async def verify(args: argparse.Namespace) -> dict:
    embedding_client = get_embedding_client()
    vector = (await embed_texts(embedding_client, model=args.embedding_model, texts=["dimension probe"]))[0]
    qdrant = get_qdrant()
    try:
        exists = await qdrant.collection_exists(args.collection)
        info = await qdrant.get_collection(args.collection) if exists else None
        return {
            "ok": bool(len(vector) == args.vector_dim and exists),
            "embedding_model": args.embedding_model,
            "embedding_dim": len(vector),
            "expected_dim": args.vector_dim,
            "collection": args.collection,
            "collection_exists": exists,
            "points_count": getattr(info, "points_count", None) if info else None,
        }
    finally:
        close = getattr(qdrant, "close", None)
        if close:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify isolated Qdrant v2 collection and embedding dimension.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--vector-dim", type=int, default=DEFAULT_VECTOR_DIM)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32" and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(json.dumps(asyncio.run(verify(parse_args(argv))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
