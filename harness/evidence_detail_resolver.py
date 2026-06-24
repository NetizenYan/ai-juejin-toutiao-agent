"""Read-only evidence detail resolver for RAG citations.

The resolver bridges source-scoped evidence IDs such as ``news:jjrb:...`` to a
reader-facing detail object. It does not call any LLM, mutate Qdrant, or write
to MySQL.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.ai_conf import settings
from config.vector_conf import CHUNK_COLLECTION, COLLECTION, get_qdrant

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSONL_PATHS = (
    PROJECT_ROOT / "work" / "econ_rag_experiment" / "clean_merged_recent_econ.jsonl",
)

SOURCE_LABELS = {
    "jjrb": "经济日报",
    "经济日报": "经济日报",
    "rmrb": "人民日报",
    "人民日报": "人民日报",
    "cctv": "央视 / 新闻联播",
    "央视": "央视 / 新闻联播",
    "新闻联播": "央视 / 新闻联播",
    "old": "站内新闻",
}


def normalize_evidence_id(evidence_id: str) -> str:
    value = str(evidence_id or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    return value


def _core_id(evidence_id: str) -> str:
    return evidence_id[len("news:") :] if evidence_id.startswith("news:") else evidence_id


def _source_and_source_doc_id(core: str) -> tuple[str | None, str | None]:
    if ":" not in core:
        return None, None
    source, source_doc_id = core.split(":", 1)
    return source or None, source_doc_id or None


def _lookup_candidates(evidence_id: str) -> list[tuple[str, Any]]:
    core = _core_id(evidence_id)
    source, source_doc_id = _source_and_source_doc_id(core)
    values: list[tuple[str, Any]] = [
        ("evidence_id", evidence_id),
        ("doc_id", core),
        ("news_id", core),
        ("parent_news_id", core),
    ]
    if source_doc_id:
        values.append(("source_doc_id", source_doc_id))
    if source and source_doc_id:
        values.append(("doc_id", f"{source}:{source_doc_id}"))
        values.append(("news_id", f"{source}:{source_doc_id}"))
        values.append(("parent_news_id", f"{source}:{source_doc_id}"))
    if core.isdigit():
        numeric_id = int(core)
        values.extend(
            [
                ("news_id", numeric_id),
                ("parent_news_id", numeric_id),
                ("id", numeric_id),
            ]
        )

    deduped: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, value in values:
        marker = (key, repr(value))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append((key, value))
    return deduped


def _default_collections() -> list[str]:
    collections = [
        settings.rag_econ_collection_name,
        CHUNK_COLLECTION,
        COLLECTION,
    ]
    out: list[str] = []
    for collection in collections:
        if collection and collection not in out:
            out.append(collection)
    return out


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clip(value: Any, limit: int) -> str:
    text_value = _compact_text(value)
    if len(text_value) <= limit:
        return text_value
    return text_value[:limit].rstrip() + "..."


def _source_label(source: Any) -> str | None:
    raw = _compact_text(source)
    if not raw:
        return None
    return SOURCE_LABELS.get(raw, raw)


def _payload_text(payload: dict[str, Any], *, prefer_parent: bool = False) -> tuple[str, str]:
    if prefer_parent:
        snippet_source = payload.get("summary") or payload.get("description") or payload.get("content")
        excerpt_source = payload.get("content") or payload.get("text") or payload.get("chunk_text") or snippet_source
    else:
        snippet_source = payload.get("snippet") or payload.get("summary") or payload.get("chunk_text") or payload.get("text")
        excerpt_source = payload.get("content") or payload.get("text") or payload.get("chunk_text") or payload.get("summary")
    return _clip(snippet_source, 260), _clip(excerpt_source, 1200)


def _detail_from_payload(
    payload: dict[str, Any],
    evidence_id: str,
    *,
    collection: str | None,
    storage: str,
    prefer_parent: bool = False,
) -> dict[str, Any]:
    source = payload.get("source") or payload.get("author")
    snippet, content_excerpt = _payload_text(payload, prefer_parent=prefer_parent)
    parent_id = (
        payload.get("parent_news_id")
        or payload.get("doc_id")
        or payload.get("news_id")
        or payload.get("id")
        or _core_id(evidence_id)
    )
    detail_available = bool(payload.get("title") or snippet or content_excerpt)
    result = {
        "evidence_id": evidence_id,
        "found": True,
        "source": _source_label(source),
        "title": payload.get("title"),
        "publish_time": payload.get("publish_time"),
        "snippet": snippet,
        "content_excerpt": content_excerpt,
        "collection": collection,
        "parent_id": parent_id,
        "chunk_index": payload.get("chunk_index"),
        "detail_available": detail_available,
        "storage": storage,
    }
    optional_fields = {
        "section": payload.get("section"),
        "category": payload.get("category"),
        "url": payload.get("url"),
        "chunk_type": payload.get("chunk_type"),
    }
    for key, value in optional_fields.items():
        if value is not None:
            result[key] = value
    return result


def _row_matches(row: dict[str, Any], evidence_id: str) -> bool:
    core = _core_id(evidence_id)
    source, source_doc_id = _source_and_source_doc_id(core)
    # Identifiers this row is actually known by — built ONLY from row fields.
    row_ids = {
        str(row.get("evidence_id") or ""),
        str(row.get("doc_id") or ""),
        str(row.get("news_id") or ""),
        str(row.get("parent_news_id") or ""),
        str(row.get("source_doc_id") or ""),
    }
    row_ids.discard("")
    # Identifiers the queried evidence_id may legitimately refer to.
    query_ids = {evidence_id, core}
    if source and source_doc_id:
        query_ids.add(f"news:{source}:{source_doc_id}")
        query_ids.add(f"{source}:{source_doc_id}")
        query_ids.add(source_doc_id)
    query_ids.discard("")
    # Match only when a row identifier equals a query identifier. (Previously the
    # query-derived ids were mixed into the row set and tested against itself, so
    # every row matched and the JSONL fallback always returned its first line.)
    return not row_ids.isdisjoint(query_ids)


async def _maybe_close_qdrant(qdrant: Any) -> None:
    close = getattr(qdrant, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def _lookup_qdrant(
    evidence_id: str,
    *,
    qdrant_factory: Any,
    collections: list[str],
) -> dict[str, Any] | None:
    qdrant = qdrant_factory()
    try:
        for collection in collections:
            for key, value in _lookup_candidates(evidence_id):
                try:
                    points, _next_offset = await qdrant.scroll(
                        collection_name=collection,
                        scroll_filter=Filter(must=[FieldCondition(key=key, match=MatchValue(value=value))]),
                        limit=1,
                        with_payload=True,
                        with_vectors=False,
                    )
                except Exception:
                    continue
                if points:
                    payload = dict((getattr(points[0], "payload", None) or {}))
                    return _detail_from_payload(
                        payload,
                        evidence_id,
                        collection=collection,
                        storage="qdrant_payload",
                    )
    finally:
        await _maybe_close_qdrant(qdrant)
    return None


def _lookup_jsonl(evidence_id: str, jsonl_paths: list[Path]) -> dict[str, Any] | None:
    for path in jsonl_paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or not _row_matches(row, evidence_id):
                    continue
                return _detail_from_payload(
                    row,
                    evidence_id,
                    collection=None,
                    storage=f"jsonl:{path}",
                    prefer_parent=True,
                )
    return None


async def _lookup_mysql(evidence_id: str, db: AsyncSession | None) -> dict[str, Any] | None:
    core = _core_id(evidence_id)
    if db is None or not core.isdigit():
        return None
    result = await db.execute(
        text(
            """
            SELECT
              n.id, n.title, n.description, n.content, n.author AS source,
              n.publish_time, c.name AS category
            FROM news n
            LEFT JOIN news_category c ON c.id = n.category_id
            WHERE n.id = :news_id
            LIMIT 1
            """
        ),
        {"news_id": int(core)},
    )
    row = result.fetchone()
    if row is None:
        return None
    payload = dict(row._mapping)
    payload["news_id"] = int(core)
    payload["parent_news_id"] = int(core)
    return _detail_from_payload(
        payload,
        evidence_id,
        collection="mysql_news_business",
        storage="mysql_news_app.news",
        prefer_parent=True,
    )


async def resolve_evidence_detail(
    evidence_id: str,
    *,
    qdrant_factory: Any = get_qdrant,
    collections: list[str] | None = None,
    jsonl_paths: list[str | Path] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    normalized_id = normalize_evidence_id(evidence_id)
    if not normalized_id:
        return {"evidence_id": normalized_id, "found": False, "error": "invalid_evidence_id"}

    collection_names = collections if collections is not None else _default_collections()
    qdrant_result = await _lookup_qdrant(
        normalized_id,
        qdrant_factory=qdrant_factory,
        collections=list(collection_names),
    )
    if qdrant_result:
        return qdrant_result

    paths = [Path(path) for path in (jsonl_paths if jsonl_paths is not None else DEFAULT_JSONL_PATHS)]
    jsonl_result = _lookup_jsonl(normalized_id, paths)
    if jsonl_result:
        return jsonl_result

    mysql_result = await _lookup_mysql(normalized_id, db)
    if mysql_result:
        return mysql_result

    return {"evidence_id": normalized_id, "found": False, "error": "evidence_not_found"}
