"""Shared RAG search adapter for the RAG MCP server and retrieval evals."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config.ai_conf import get_embedding_client, settings
from config.vector_conf import CHUNK_COLLECTION, assert_meta_matches, get_qdrant
from harness.rag_query_router import (
    TIMELINE_RECENT_TRIGGERS,
    is_econ_finance_query,
    matched_source_terms,
    route_rag_query,
)
from harness.rag_ranking import (
    normalize_publish_metadata,
    quality_aware_hybrid_rerank,
    quality_score,
    recency_score,
    time_aware_hybrid_rerank,
)


SOURCE_VALUE_ALIASES = {
    "经济日报": ("jjrb", "经济日报"),
    "人民日报": ("rmrb", "人民日报"),
    "新闻联播": ("新闻联播",),
    "央视": ("央视", "新闻联播"),
    "央视新闻": ("央视新闻", "新闻联播"),
    "新华社": ("新华社",),
}


def _matched_source_values(query: str) -> list[str]:
    values: list[str] = []
    for term in matched_source_terms(query):
        aliases = SOURCE_VALUE_ALIASES.get(term, (term,))
        for alias in aliases:
            if alias not in values:
                values.append(alias)
    return values


def _source_filter_values(query: str) -> list[str]:
    terms = matched_source_terms(query)
    if len(terms) > 1:
        return []
    return _matched_source_values(query)


def _query_filter(chunk_type: str | None, source_values: list[str] | None = None) -> Filter | None:
    must = []
    if chunk_type:
        must.append(FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type)))
    if source_values:
        must.append(FieldCondition(key="source", match=MatchValue(value=source_values[0])))
    return Filter(must=must) if must else None


def _body_evidence_filter(parent_news_id: int) -> Filter:
    return Filter(
        must=[
            FieldCondition(key="chunk_type", match=MatchValue(value="body")),
            FieldCondition(key="parent_news_id", match=MatchValue(value=parent_news_id)),
        ]
    )


async def _embed_query(query: str, embedding_client_factory: Callable[[], Any]) -> list[float]:
    client = embedding_client_factory()
    response = await client.embeddings.create(model=settings.embedding_model, input=[query])
    if not response.data or not response.data[0].embedding:
        raise RuntimeError("embedding service returned no vector")
    return list(response.data[0].embedding)


async def _query_points(
    qdrant: Any,
    vector: list[float],
    limit: int,
    chunk_type_filter: str | None,
    collection_name: str,
    source_values: list[str] | None = None,
) -> tuple[list[Any], bool]:
    query_filter = _query_filter(chunk_type_filter, source_values)
    kwargs = {
        "collection_name": collection_name,
        "query": vector,
        "limit": limit,
        "with_payload": True,
    }
    if query_filter is not None:
        kwargs["query_filter"] = query_filter

    try:
        result = await qdrant.query_points(**kwargs)
    except TypeError:
        if query_filter is None:
            raise
        kwargs.pop("query_filter", None)
        result = await qdrant.query_points(**kwargs)
        return list(getattr(result, "points", []) or []), True

    points = list(getattr(result, "points", []) or [])
    if points or query_filter is None:
        return points, False
    if source_values:
        return [], False

    # Claude's existing chunk index has no chunk_type payload. Falling back here
    # keeps the runnable chain alive while Codex summary/body indexes are adopted.
    kwargs.pop("query_filter", None)
    result = await qdrant.query_points(**kwargs)
    return list(getattr(result, "points", []) or []), True


def _item_evidence_id(item: dict) -> str | None:
    if item.get("evidence_id"):
        return str(item["evidence_id"])
    if item.get("id") is not None:
        return f"news:{item['id']}"
    return None


def _point_to_item(point: Any) -> dict:
    payload = getattr(point, "payload", None) or {}
    news_id = payload.get("news_id") or payload.get("id") or payload.get("parent_news_id")
    chunk_text = payload.get("chunk_text") or payload.get("summary") or payload.get("text") or ""
    evidence_id = payload.get("evidence_id") or (f"news:{news_id}" if news_id is not None else None)
    return {
        "id": news_id,
        "parent_news_id": payload.get("parent_news_id") or news_id,
        "chunk_index": payload.get("chunk_index"),
        "chunk_type": payload.get("chunk_type"),
        "title": payload.get("title"),
        "summary": chunk_text,
        "text": payload.get("text") or chunk_text,
        "publish_ts": payload.get("publish_ts", 0),
        "publish_time": payload.get("publish_time"),
        "source": payload.get("source") or payload.get("author"),
        "section": payload.get("section"),
        "category": payload.get("category"),
        "score": round(float(getattr(point, "score", 0.0) or 0.0), 4),
        "evidence_id": evidence_id,
    }


def _points_to_items(points: list[Any]) -> list[dict]:
    return [_point_to_item(point) for point in points]


def _has_recent_intent(query: str, route: Any) -> bool:
    if getattr(route, "query_type", None) == "timeline_or_recent":
        return True
    return any(trigger in (query or "") for trigger in TIMELINE_RECENT_TRIGGERS)


STRICT_RECENT_TRIGGERS = (
    "最近",
    "近期",
    "近来",
    "近段时间",
    "最新",
    "今天",
    "昨天",
    "本周",
    "现在",
)


def _recent_recency_floor(query: str, route: Any) -> float:
    normalized = query or ""
    if any(trigger in normalized for trigger in STRICT_RECENT_TRIGGERS):
        return 0.80
    if _has_recent_intent(normalized, route):
        return 0.45
    return 0.0


def _rerank_items(query: str, items: list[dict], ranking: str, route: Any) -> tuple[list[dict], bool]:
    if ranking != "hybrid":
        return [normalize_publish_metadata(item) for item in items], False
    if _has_recent_intent(query, route):
        return time_aware_hybrid_rerank(query, items), True
    return quality_aware_hybrid_rerank(query, items), False


def _filter_severe_low_quality(items: list[dict], min_remaining: int) -> tuple[list[dict], int]:
    if not items:
        return items, 0
    filtered = [item for item in items if quality_score(item) > 0.35]
    removed = len(items) - len(filtered)
    if removed and len(filtered) >= min_remaining:
        return filtered, removed
    return items, 0


def _compact_query(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?《》（）()·:：\-_]+", "", text or "")


def _title_overlaps_query(item: dict, query_compact: str) -> bool:
    if not query_compact:
        return False
    title = _compact_query(str(item.get("title") or ""))
    if not title or len(title) < 6:
        return False
    best = 0
    previous = [0] * (len(query_compact) + 1)
    for title_char in title:
        current = [0]
        for index, query_char in enumerate(query_compact, 1):
            value = previous[index - 1] + 1 if title_char == query_char else 0
            current.append(value)
            if value > best:
                best = value
        previous = current
    return best >= 6


def _filter_stale_recent_items(items: list[dict], query: str, route: Any) -> tuple[list[dict], int]:
    if not items:
        return items, 0
    floor = _recent_recency_floor(query, route)
    query_compact = _compact_query(query)
    filtered = [
        item for item in items
        if recency_score(item) >= floor or _title_overlaps_query(item, query_compact)
    ]
    return filtered, len(items) - len(filtered)


def _select_collection(query: str) -> tuple[str, str]:
    test_env = settings.app_env in {"test", "testing"}
    econ_query = is_econ_finance_query(query)
    source_values = _matched_source_values(query)
    if any(value in {"新闻联播", "央视", "央视新闻"} for value in source_values):
        return CHUNK_COLLECTION, "default"
    if settings.rag_econ_collection_enabled and settings.rag_econ_collection_name and (econ_query or test_env):
        reason = "test_env" if test_env and not econ_query else "econ_finance_query"
        return settings.rag_econ_collection_name, reason
    return CHUNK_COLLECTION, "default"


def _apply_source_preference(query: str, items: list[dict]) -> list[dict]:
    terms = matched_source_terms(query)
    values = _matched_source_values(query)
    if not terms and not values:
        return items
    preferred = [
        item for item in items
        if any(term in str(item.get("source") or "") or term in str(item.get("title") or "") for term in terms)
        or any(value in str(item.get("source") or "") or value in str(item.get("title") or "") for value in values)
    ]
    if not preferred:
        return items
    preferred_ids = {id(item) for item in preferred}
    return preferred + [item for item in items if id(item) not in preferred_ids]


def _dedupe_items(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        key = str(_item_evidence_id(item) or item.get("parent_news_id") or item.get("id") or id(item))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _with_body_fallback(summary_items: list[dict], body_items: list[dict], final_limit: int, slots: int) -> tuple[list[dict], int]:
    slots = max(0, min(int(slots or 0), max(1, final_limit)))
    summary_slots = max(0, final_limit - slots)
    items: list[dict] = []
    seen_keys: set[str] = set()
    seen_parents: set[str] = set()

    def add(item: dict) -> bool:
        parent = str(item.get("parent_news_id") or item.get("id") or "")
        key = str(_item_evidence_id(item) or parent or id(item))
        if key in seen_keys:
            return False
        seen_keys.add(key)
        if parent:
            seen_parents.add(parent)
        items.append(item)
        return True

    for item in summary_items[:summary_slots]:
        add(item)

    added_body = 0
    for item in body_items:
        if added_body >= slots:
            break
        parent = str(item.get("parent_news_id") or item.get("id") or "")
        if parent and parent in seen_parents:
            continue
        if add(item):
            added_body += 1

    for item in summary_items[summary_slots:]:
        if len(items) >= final_limit:
            break
        add(item)
    return items[:final_limit], added_body


async def _attach_body_evidence(
    qdrant: Any,
    result: dict,
    body_chunks_per_parent: int,
    collection_name: str,
) -> None:
    if not hasattr(qdrant, "scroll"):
        return
    per_parent = max(1, int(body_chunks_per_parent or 1))
    body_items: list[dict] = []
    seen_parent_ids: set[int] = set()
    for item in result.get("items") or []:
        try:
            parent_id = int(item.get("parent_news_id") or item.get("id"))
        except (TypeError, ValueError):
            continue
        if parent_id in seen_parent_ids:
            continue
        seen_parent_ids.add(parent_id)
        try:
            points, _next_offset = await qdrant.scroll(
                collection_name=collection_name,
                scroll_filter=_body_evidence_filter(parent_id),
                limit=per_parent,
                with_payload=True,
            )
        except Exception:
            continue
        body_items.extend(_points_to_items(list(points or [])[:per_parent]))

    result["body_evidence"] = body_items
    result["body_evidence_ids"] = [
        evidence_id for item in body_items if (evidence_id := _item_evidence_id(item))
    ]


async def search_news_rag(
    query: str,
    limit: int = 50,
    *,
    ranking: str | None = None,
    chunk_type_filter: str | None = None,
    expand_body_evidence: bool | None = None,
    body_chunks_per_parent: int | None = None,
    body_fallback_slots: int | None = None,
    query_router_enabled: bool | None = None,
    tool_name: str = "news_rag_search",
    embedding_client_factory: Callable[[], Any] = get_embedding_client,
    qdrant_factory: Callable[[], Any] = get_qdrant,
    assert_meta_matches_fn: Callable[[str, int], None] = assert_meta_matches,
) -> dict:
    final_limit = max(1, min(int(limit), 80))
    candidate_limit = max(final_limit, int(settings.rag_recall_limit or 50))
    effective_ranking = ranking or settings.rag_ranking
    effective_chunk_type_filter = settings.rag_chunk_type_filter if chunk_type_filter is None else chunk_type_filter
    effective_expand_body = settings.rag_expand_body_evidence if expand_body_evidence is None else expand_body_evidence
    effective_body_chunks = settings.rag_body_chunks_per_parent if body_chunks_per_parent is None else body_chunks_per_parent
    configured_body_slots = settings.rag_body_fallback_slots if body_fallback_slots is None else body_fallback_slots
    effective_router_enabled = settings.rag_query_router_enabled if query_router_enabled is None else query_router_enabled
    vector = await _embed_query(query, embedding_client_factory)
    assert_meta_matches_fn(settings.embedding_model, len(vector))

    route = route_rag_query(
        query,
        enabled=effective_router_enabled,
        default_body_fallback_slots=configured_body_slots,
    )
    collection_name, collection_reason = _select_collection(query)
    effective_body_slots = max(0, int(route.body_fallback_slots or 0))
    source_values = _source_filter_values(query) if route.query_type == "source_constrained" else []
    qdrant = qdrant_factory()

    summary_points, filter_fallback_used = await _query_points(
        qdrant, vector, candidate_limit, effective_chunk_type_filter, collection_name, source_values
    )
    summary_items = _points_to_items(summary_points)
    summary_items, time_aware_ranking = _rerank_items(query, summary_items, effective_ranking, route)
    summary_items, summary_low_quality_filtered = _filter_severe_low_quality(summary_items, final_limit)
    stale_filtered = 0
    if _has_recent_intent(query, route):
        summary_items, stale_filtered = _filter_stale_recent_items(summary_items, query, route)
    summary_items = _apply_source_preference(query, summary_items)

    body_added = 0
    body_low_quality_filtered = 0
    body_stale_filtered = 0
    if effective_body_slots:
        body_points, _body_filter_fallback = await _query_points(
            qdrant, vector, candidate_limit, "body", collection_name, source_values
        )
        body_items = _points_to_items(body_points)
        body_items, _body_time_aware = _rerank_items(query, body_items, effective_ranking, route)
        body_items, body_low_quality_filtered = _filter_severe_low_quality(body_items, effective_body_slots)
        if _has_recent_intent(query, route):
            body_items, body_stale_filtered = _filter_stale_recent_items(body_items, query, route)
        items, body_added = _with_body_fallback(summary_items, body_items, final_limit, effective_body_slots)
    else:
        items = summary_items[:final_limit]

    result = {
        "tool": tool_name,
        "items": _dedupe_items(items)[:final_limit],
        "rag_route": route.to_dict(),
        "ranking": effective_ranking,
        "candidate_limit": candidate_limit,
        "chunk_type_filter": effective_chunk_type_filter,
        "chunk_type_filter_fallback_used": filter_fallback_used,
        "body_fallback_slots": effective_body_slots,
        "body_fallback_used": body_added,
        "time_aware_ranking": time_aware_ranking,
        "low_quality_filtered": summary_low_quality_filtered + body_low_quality_filtered,
        "stale_time_filtered": stale_filtered + body_stale_filtered,
        "collection_name": collection_name,
        "collection_route": collection_reason,
    }
    result["evidence_ids"] = [
        evidence_id for item in result["items"] if (evidence_id := _item_evidence_id(item))
    ]

    if effective_expand_body:
        await _attach_body_evidence(qdrant, result, effective_body_chunks, collection_name)

    return result
