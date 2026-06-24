"""Build the isolated v2 retrieval store.

This script reads the already-cleaned local economy corpus, writes parent/chunk
metadata to a new PostgreSQL database, and writes bge-m3 vectors to a new
Qdrant collection. It never touches Docker MySQL or legacy Qdrant collections.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg
from openai import AsyncOpenAI
from qdrant_client.models import Distance, PointStruct, VectorParams

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.ai_conf import settings  # noqa: E402
from config.vector_conf import get_qdrant  # noqa: E402
from scripts.econ_candidate_chunk_index import (  # noqa: E402
    DEFAULT_DATASET,
    base_payload,
    iter_docs,
    make_points_for_doc,
    stable_point_id,
)


DEFAULT_COLLECTION = os.getenv("QDRANT_UNIFIED_COLLECTION", "news_chunks_v2")
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_V2_MODEL", "bge-m3")
DEFAULT_VECTOR_DIM = int(os.getenv("EMBEDDING_V2_DIM", "1024"))
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "rebuild_pipeline_v2_report_20260622.json"
DEFAULT_SCHEMA = PROJECT_ROOT / "sql" / "pg_rebuild.sql"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def pg_config_from_env(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or argparse.Namespace()
    return {
        "host": getattr(args, "pg_host", None) or os.getenv("PG_HOST", "127.0.0.1"),
        "port": int(getattr(args, "pg_port", None) or _int_env("PG_PORT", 5433)),
        "user": getattr(args, "pg_user", None) or os.getenv("PG_USER", "postgres"),
        "password": getattr(args, "pg_password", None) or os.getenv("PG_PASSWORD", "postgres"),
        "database": getattr(args, "pg_database", None) or os.getenv("PG_DATABASE", "toutiao_agent"),
    }


def _metadata_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": doc.get("section") or "",
        "category": doc.get("category") or "",
        "old_news_id": doc.get("old_news_id"),
        "url": doc.get("url") or "",
    }


def parent_row(doc: dict[str, Any]) -> dict[str, Any]:
    payload = base_payload(doc)
    content = str(doc.get("content") or "")
    evidence_id = str(doc.get("evidence_id") or f"news:{payload.get('doc_id') or payload.get('news_id')}")
    return {
        "evidence_id": evidence_id,
        "doc_id": str(doc.get("doc_id") or payload.get("doc_id") or ""),
        "source_code": str(doc.get("source") or ""),
        "source_doc_id": str(doc.get("source_doc_id") or ""),
        "title": str(doc.get("title") or ""),
        "publish_time": doc.get("publish_time"),
        "publish_ts": int(doc.get("publish_ts") or 0),
        "section": str(doc.get("section") or ""),
        "category": str(doc.get("category") or ""),
        "url": str(doc.get("url") or ""),
        "content": content,
        "content_length": len(content),
        "metadata": _metadata_from_doc(doc),
    }


def chunk_rows_for_doc(
    doc: dict[str, Any],
    *,
    collection: str,
    embedding_model: str,
    vector_dim: int,
    body_size: int,
    body_overlap: int,
    max_body_chunks: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, payload, embed_text in make_points_for_doc(
        doc,
        collection=collection,
        body_size=body_size,
        body_overlap=body_overlap,
        max_body_chunks=max_body_chunks,
    ):
        point_id = stable_point_id(key)
        chunk_id = f"{payload.get('evidence_id') or key}|{payload.get('chunk_type')}|{payload.get('chunk_index')}"
        rows.append({
            "evidence_id": payload.get("evidence_id") or parent_row(doc)["evidence_id"],
            "chunk_id": chunk_id,
            "chunk_type": str(payload.get("chunk_type") or ""),
            "chunk_index": int(payload.get("chunk_index") or 0),
            "chunk_text": str(payload.get("chunk_text") or payload.get("text") or ""),
            "collection_name": collection,
            "vector_model": embedding_model,
            "vector_dim": int(vector_dim),
            "qdrant_point_id": int(point_id),
            "metadata": {
                "doc_id": payload.get("doc_id"),
                "source": payload.get("source"),
                "source_doc_id": payload.get("source_doc_id"),
                "publish_time": payload.get("publish_time"),
                "publish_ts": payload.get("publish_ts"),
                "title": payload.get("title"),
                "embed_text": embed_text,
            },
            "payload": payload,
            "embed_text": embed_text,
        })
    return rows


def estimate_dataset(
    dataset: Path,
    *,
    max_docs: int | None,
    collection: str,
    embedding_model: str,
    vector_dim: int,
    body_size: int,
    body_overlap: int,
    max_body_chunks: int,
) -> dict[str, Any]:
    docs = 0
    points = 0
    source_counts: Counter[str] = Counter()
    chunk_type_counts: Counter[str] = Counter()
    for doc in iter_docs(dataset, max_docs):
        docs += 1
        source_counts[str(doc.get("source") or "")] += 1
        rows = chunk_rows_for_doc(
            doc,
            collection=collection,
            embedding_model=embedding_model,
            vector_dim=vector_dim,
            body_size=body_size,
            body_overlap=body_overlap,
            max_body_chunks=max_body_chunks,
        )
        points += len(rows)
        for row in rows:
            chunk_type_counts[row["chunk_type"]] += 1
    return {
        "dataset": str(dataset),
        "collection": collection,
        "embedding_model": embedding_model,
        "vector_dim": int(vector_dim),
        "docs": docs,
        "estimated_points": points,
        "source_counts": dict(source_counts),
        "chunk_type_counts": dict(chunk_type_counts),
        "body_size": body_size,
        "body_overlap": body_overlap,
        "max_body_chunks": max_body_chunks,
    }


def get_embedding_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key or "not-needed",
    )


async def embed_texts(client: Any, *, model: str, texts: list[str]) -> list[list[float]]:
    response = await client.embeddings.create(model=model, input=texts)
    return [list(item.embedding) for item in response.data]


async def ensure_pg_schema(conn: asyncpg.Connection, schema_path: Path = DEFAULT_SCHEMA) -> None:
    await conn.execute(schema_path.read_text(encoding="utf-8"))


async def insert_parent_rows(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO news_unified (
          evidence_id, doc_id, source_code, source_doc_id, title, publish_time,
          publish_ts, section, category, url, content, content_length, metadata
        ) VALUES (
          $1, $2, $3, $4, $5, NULLIF($6, '')::timestamptz,
          $7, $8, $9, $10, $11, $12, $13::jsonb
        )
        ON CONFLICT (evidence_id) DO UPDATE SET
          title = EXCLUDED.title,
          publish_time = EXCLUDED.publish_time,
          publish_ts = EXCLUDED.publish_ts,
          content = EXCLUDED.content,
          content_length = EXCLUDED.content_length,
          metadata = EXCLUDED.metadata,
          updated_at = now()
        """,
        [
            (
                row["evidence_id"],
                row["doc_id"],
                row["source_code"],
                row["source_doc_id"],
                row["title"],
                str(row.get("publish_time") or ""),
                row["publish_ts"],
                row["section"],
                row["category"],
                row["url"],
                row["content"],
                row["content_length"],
                json.dumps(row["metadata"], ensure_ascii=False),
            )
            for row in rows
        ],
    )


async def insert_chunk_rows(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO news_chunks_meta (
          evidence_id, chunk_id, chunk_type, chunk_index, chunk_text,
          collection_name, vector_model, vector_dim, qdrant_point_id, metadata
        ) VALUES (
          $1, $2, $3, $4, $5,
          $6, $7, $8, $9, $10::jsonb
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
          chunk_text = EXCLUDED.chunk_text,
          collection_name = EXCLUDED.collection_name,
          vector_model = EXCLUDED.vector_model,
          vector_dim = EXCLUDED.vector_dim,
          qdrant_point_id = EXCLUDED.qdrant_point_id,
          metadata = EXCLUDED.metadata
        """,
        [
            (
                row["evidence_id"],
                row["chunk_id"],
                row["chunk_type"],
                row["chunk_index"],
                row["chunk_text"],
                row["collection_name"],
                row["vector_model"],
                row["vector_dim"],
                row["qdrant_point_id"],
                json.dumps(row["metadata"], ensure_ascii=False),
            )
            for row in rows
        ],
    )


async def ensure_qdrant_collection(client: Any, *, collection: str, vector_dim: int, recreate: bool, append: bool) -> None:
    exists = await client.collection_exists(collection)
    if exists and recreate:
        await client.delete_collection(collection)
        exists = False
    if exists and not append and not recreate:
        raise RuntimeError(f"collection already exists: {collection}; pass --recreate or --append")
    if not exists:
        await client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
        )


async def truncate_v2_pg(conn: asyncpg.Connection) -> None:
    await conn.execute("TRUNCATE TABLE news_chunks_meta CASCADE")
    await conn.execute("TRUNCATE TABLE news_unified CASCADE")


async def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    dataset = Path(args.dataset)
    report_path = Path(args.report)
    estimate = estimate_dataset(
        dataset,
        max_docs=args.max_docs,
        collection=args.collection,
        embedding_model=args.embedding_model,
        vector_dim=args.vector_dim,
        body_size=args.body_size,
        body_overlap=args.body_overlap,
        max_body_chunks=args.max_body_chunks,
    )
    if args.dry_run:
        output = {**estimate, "dry_run": True}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return output

    embedding_client = get_embedding_client()
    probe = (await embed_texts(embedding_client, model=args.embedding_model, texts=["dimension probe"]))[0]
    if len(probe) != int(args.vector_dim):
        raise RuntimeError(f"embedding dimension mismatch: expected {args.vector_dim}, got {len(probe)}")

    qdrant = get_qdrant()
    await ensure_qdrant_collection(
        qdrant,
        collection=args.collection,
        vector_dim=args.vector_dim,
        recreate=bool(args.recreate),
        append=bool(args.append),
    )
    conn = await asyncpg.connect(**pg_config_from_env(args))
    await ensure_pg_schema(conn)
    if args.recreate:
        await truncate_v2_pg(conn)

    pending_parents: list[dict[str, Any]] = []
    pending_chunks: list[dict[str, Any]] = []
    pending_texts: list[str] = []
    indexed_points = 0
    docs = 0
    source_counts: Counter[str] = Counter()
    chunk_type_counts: Counter[str] = Counter()

    async def flush() -> None:
        nonlocal indexed_points
        if not pending_chunks:
            return
        vectors = await embed_texts(embedding_client, model=args.embedding_model, texts=pending_texts)
        points = [
            PointStruct(id=row["qdrant_point_id"], vector=vector, payload=row["payload"])
            for row, vector in zip(pending_chunks, vectors)
        ]
        await insert_parent_rows(conn, pending_parents)
        await insert_chunk_rows(conn, pending_chunks)
        await qdrant.upsert(collection_name=args.collection, points=points)
        indexed_points += len(points)
        print(f"indexed {indexed_points}/{estimate['estimated_points']}")
        pending_parents.clear()
        pending_chunks.clear()
        pending_texts.clear()

    try:
        for doc in iter_docs(dataset, args.max_docs):
            docs += 1
            source_counts[str(doc.get("source") or "")] += 1
            parent = parent_row(doc)
            pending_parents.append(parent)
            chunk_rows = chunk_rows_for_doc(
                doc,
                collection=args.collection,
                embedding_model=args.embedding_model,
                vector_dim=args.vector_dim,
                body_size=args.body_size,
                body_overlap=args.body_overlap,
                max_body_chunks=args.max_body_chunks,
            )
            for row in chunk_rows:
                chunk_type_counts[row["chunk_type"]] += 1
                pending_chunks.append(row)
                pending_texts.append(row["embed_text"])
                if len(pending_chunks) >= args.batch_size:
                    await flush()
        await flush()
        info = await qdrant.get_collection(args.collection)
        pg_counts = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM news_unified) AS parents, "
            "(SELECT count(*) FROM news_chunks_meta) AS chunks"
        )
        output = {
            **estimate,
            "dry_run": False,
            "docs_indexed": docs,
            "points_indexed": indexed_points,
            "qdrant_points_count": getattr(info, "points_count", None),
            "pg_parent_count": int(pg_counts["parents"]),
            "pg_chunk_count": int(pg_counts["chunks"]),
            "indexed_source_counts": dict(source_counts),
            "indexed_chunk_type_counts": dict(chunk_type_counts),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return output
    finally:
        await conn.close()
        close = getattr(qdrant, "close", None)
        if close:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build isolated PG + Qdrant v2 retrieval store.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--vector-dim", type=int, default=DEFAULT_VECTOR_DIM)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--max-docs", type=int)
    parser.add_argument("--body-size", type=int, default=600)
    parser.add_argument("--body-overlap", type=int, default=120)
    parser.add_argument("--max-body-chunks", type=int, default=8)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full", action="store_true", help="Documentation flag; default already processes all docs.")
    parser.add_argument("--pg-host", default=os.getenv("PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-port", type=int, default=_int_env("PG_PORT", 5433))
    parser.add_argument("--pg-user", default=os.getenv("PG_USER", "postgres"))
    parser.add_argument("--pg-password", default=os.getenv("PG_PASSWORD", "postgres"))
    parser.add_argument("--pg-database", default=os.getenv("PG_DATABASE", "toutiao_agent"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32" and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(build(parse_args(argv)))


if __name__ == "__main__":
    main()
