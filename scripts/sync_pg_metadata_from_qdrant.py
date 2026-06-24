"""Sync Qdrant payload metadata into the isolated PostgreSQL v2 tables.

This is a metadata-only alignment utility. It reads existing Qdrant points and
upserts parent/chunk rows into PostgreSQL. It does not create embeddings, modify
vectors, rebuild Qdrant collections, or delete existing PG rows.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=False)

from config.vector_conf import get_qdrant  # noqa: E402
from scripts.rebuild_pipeline import (  # noqa: E402
    ensure_pg_schema,
    insert_chunk_rows,
    insert_parent_rows,
    pg_config_from_env,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _evidence_id(payload: dict[str, Any]) -> str:
    evidence_id = _text(payload.get("evidence_id"))
    if evidence_id:
        return evidence_id
    doc_id = _text(payload.get("doc_id") or payload.get("news_id") or payload.get("parent_news_id"))
    if doc_id.startswith("news:"):
        return doc_id
    return f"news:{doc_id}" if doc_id else ""


def _parent_content(payload: dict[str, Any]) -> str:
    return _text(payload.get("summary") or payload.get("content") or payload.get("text") or payload.get("chunk_text"))


def parent_row_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    content = _parent_content(payload)
    return {
        "evidence_id": _evidence_id(payload),
        "doc_id": _text(payload.get("doc_id") or payload.get("news_id") or payload.get("parent_news_id")),
        "source_code": _text(payload.get("source") or payload.get("source_code")),
        "source_doc_id": _text(payload.get("source_doc_id")),
        "title": _text(payload.get("title")),
        "publish_time": _text(payload.get("publish_time")),
        "publish_ts": _int(payload.get("publish_ts")),
        "section": _text(payload.get("section")),
        "category": _text(payload.get("category")),
        "url": _text(payload.get("url")),
        "content": content,
        "content_length": len(content),
        "metadata": {
            "source": _text(payload.get("source") or payload.get("source_code")),
            "source_doc_id": _text(payload.get("source_doc_id")),
            "api_embedding_model": _text(payload.get("api_embedding_model")),
        },
    }


def chunk_row_from_point(
    *,
    point_id: int,
    payload: dict[str, Any],
    collection: str,
    vector_model: str,
    vector_dim: int,
) -> dict[str, Any]:
    evidence_id = _evidence_id(payload)
    chunk_type = _text(payload.get("chunk_type") or "body")
    chunk_index = _int(payload.get("chunk_index"))
    model = _text(payload.get("api_embedding_model")) or vector_model
    chunk_text = _text(payload.get("chunk_text") or payload.get("text") or payload.get("summary"))
    return {
        "evidence_id": evidence_id,
        "chunk_id": f"{collection}|{evidence_id}|{chunk_type}|{chunk_index}|{point_id}",
        "chunk_type": chunk_type,
        "chunk_index": chunk_index,
        "chunk_text": chunk_text,
        "collection_name": collection,
        "vector_model": model,
        "vector_dim": int(vector_dim),
        "qdrant_point_id": int(point_id),
        "metadata": {
            "doc_id": _text(payload.get("doc_id") or payload.get("news_id") or payload.get("parent_news_id")),
            "source": _text(payload.get("source") or payload.get("source_code")),
            "source_doc_id": _text(payload.get("source_doc_id")),
            "publish_time": _text(payload.get("publish_time")),
            "publish_ts": _int(payload.get("publish_ts")),
            "title": _text(payload.get("title")),
            "url": _text(payload.get("url")),
        },
    }


def _merge_parent(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    if candidate["content_length"] > existing["content_length"]:
        existing["content"] = candidate["content"]
        existing["content_length"] = candidate["content_length"]
    for key in ("doc_id", "source_code", "source_doc_id", "title", "publish_time", "publish_ts", "section", "category", "url"):
        if not existing.get(key) and candidate.get(key):
            existing[key] = candidate[key]
    existing["metadata"] = {**existing.get("metadata", {}), **candidate.get("metadata", {})}
    return existing


async def sync_collection(args: argparse.Namespace) -> dict[str, Any]:
    qdrant = get_qdrant()
    conn = await asyncpg.connect(**pg_config_from_env(args))
    total_points = 0
    inserted_chunks = 0
    inserted_parent_batches = 0
    next_offset: Any = None
    try:
        await ensure_pg_schema(conn)
        while True:
            points, next_offset = await qdrant.scroll(
                collection_name=args.collection,
                limit=args.batch_size,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            parents: dict[str, dict[str, Any]] = {}
            chunks: list[dict[str, Any]] = []
            for point in points:
                payload = dict(point.payload or {})
                evidence_id = _evidence_id(payload)
                if not evidence_id:
                    continue
                parent = parent_row_from_payload(payload)
                parents[evidence_id] = _merge_parent(parents.get(evidence_id), parent)
                chunks.append(
                    chunk_row_from_point(
                        point_id=int(point.id),
                        payload=payload,
                        collection=args.collection,
                        vector_model=args.vector_model,
                        vector_dim=args.vector_dim,
                    )
                )

            if parents:
                await insert_parent_rows(conn, list(parents.values()))
                inserted_parent_batches += len(parents)
            if chunks:
                await insert_chunk_rows(conn, chunks)
                inserted_chunks += len(chunks)
            total_points += len(points)

            if next_offset is None:
                break

        counts = await conn.fetchrow(
            """
            SELECT
              count(*) FILTER (WHERE collection_name = $1) AS chunks,
              count(DISTINCT evidence_id) FILTER (WHERE collection_name = $1) AS parents
            FROM news_chunks_meta
            """,
            args.collection,
        )
        return {
            "collection": args.collection,
            "vector_model": args.vector_model,
            "vector_dim": int(args.vector_dim),
            "qdrant_points_scanned": total_points,
            "parent_rows_touched": inserted_parent_batches,
            "chunk_rows_touched": inserted_chunks,
            "pg_collection_chunks": int(counts["chunks"] or 0),
            "pg_collection_parents": int(counts["parents"] or 0),
        }
    finally:
        await conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Qdrant payload metadata into PG v2 tables.")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--vector-model", required=True)
    parser.add_argument("--vector-dim", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--pg-host", default=os.getenv("PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("PG_PORT", "5433")))
    parser.add_argument("--pg-user", default=os.getenv("PG_USER", "postgres"))
    parser.add_argument("--pg-password", default=os.getenv("PG_PASSWORD", "postgres"))
    parser.add_argument("--pg-database", default=os.getenv("PG_DATABASE", "toutiao_agent"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32" and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    result = asyncio.run(sync_collection(parse_args(argv)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
