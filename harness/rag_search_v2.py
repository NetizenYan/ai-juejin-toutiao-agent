"""Unified v2 RAG search adapter — 3.2-D Intent-aware Hybrid Retrieval.

Retrieval channels (all hit the *existing* news_chunks_v2 collection):
  1. Dense   — bge-m3 vector query → top-N
  2. Title keyword — Qdrant MatchText scroll on ``title`` → top-N
  3. Chunk keyword — Qdrant MatchText scroll on ``chunk_text`` → top-N

Channels are selected by ``QueryIntent.retrieval_plan``; results are merged,
deduped, and passed through an intent-aware light rerank.

Constraints carried from 3.2-C:
  - multi-query OFF by default
  - source/date hard-filter only on explicit user mention
  - no MySQL writes, no collection rebuild, no re-embedding
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from typing import Any

from openai import AsyncOpenAI
from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

from config.ai_conf import settings
from config.vector_conf import get_qdrant
from harness.query_intent import QueryIntent, parse_query_intent
from harness.rag_query_router import (
    SOURCE_TRIGGERS,
    is_econ_finance_query,
    route_rag_query,
)
from harness.rag_search import (
    _apply_source_preference,
    _attach_body_evidence,
    _dedupe_items,
    _filter_severe_low_quality,
    _filter_stale_recent_items,
    _has_recent_intent,
    _points_to_items,
    _query_points,
    _rerank_items,
    _source_filter_values,
    _with_body_fallback,
)


DEFAULT_V2_COLLECTION = os.getenv("QDRANT_UNIFIED_COLLECTION", "news_chunks_v2")
DEFAULT_V2_EMBEDDING_MODEL = os.getenv("EMBEDDING_V2_MODEL", "bge-m3")
DEFAULT_V2_VECTOR_DIM = int(os.getenv("EMBEDDING_V2_DIM", "1024"))
DEFAULT_V2_TOP_K = int(os.getenv("RAG_V2_QDRANT_TOP_K", "20"))
RAG_V2_MULTI_QUERY = os.getenv("RAG_V2_MULTI_QUERY", "0") == "1"
_KEYWORD_SCROLL_LIMIT = int(os.getenv("RAG_V2_KEYWORD_LIMIT", "20"))

_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_MAX = 256

_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "经济日报": ("jjrb", "经济日报"),
    "人民日报": ("rmrb", "人民日报"),
    "新闻联播": ("新闻联播",),
    "央视": ("央视", "新闻联播"),
    "央视新闻": ("央视新闻", "新闻联播"),
    "新华社": ("新华社",),
    "中国日报": ("中国日报",),
    "证券时报": ("证券时报",),
    "财新": ("财新",),
}


# ---------------------------------------------------------------------------
# Embedding (with LRU cache)
# ---------------------------------------------------------------------------

def get_v2_embedding_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key or "not-needed",
    )


async def _embed_query_v2(
    query: str,
    *,
    embedding_model: str,
    expected_dim: int,
    embedding_client_factory: Callable[[], Any],
) -> tuple[list[float], float]:
    start = time.perf_counter()
    cache_key = f"{embedding_model}:{query}"
    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        return cached, (time.perf_counter() - start) * 1000

    client = embedding_client_factory()
    response = await client.embeddings.create(model=embedding_model, input=[query])
    if not response.data or not response.data[0].embedding:
        raise RuntimeError("embedding service returned no vector")
    vector = list(response.data[0].embedding)
    if len(vector) != int(expected_dim):
        raise RuntimeError(
            f"v2 embedding dimension mismatch: expected {expected_dim}, got {len(vector)}"
        )
    if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
        del _EMBEDDING_CACHE[next(iter(_EMBEDDING_CACHE))]
    _EMBEDDING_CACHE[cache_key] = vector
    return vector, (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# Qdrant keyword scroll helpers
# ---------------------------------------------------------------------------

async def _keyword_scroll(
    qdrant: Any,
    collection: str,
    field: str,
    terms: list[str],
    *,
    limit: int = 20,
    chunk_type_filter: str | None = None,
    source_values: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Scroll Qdrant by MatchText on *field* for any of *terms*."""
    if not terms:
        return []
    should = [FieldCondition(key=field, match=MatchText(text=t)) for t in terms[:4]]
    must: list[Any] = []
    if chunk_type_filter:
        must.append(FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type_filter)))
    if source_values:
        must.append(FieldCondition(key="source", match=MatchValue(value=source_values[0])))
    scroll_filter = Filter(must=must, should=should) if must else Filter(should=should)
    try:
        points, _ = await qdrant.scroll(
            collection_name=collection,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return _points_to_items(list(points or []))
    except Exception:
        return []


async def _evidence_id_scroll(
    qdrant: Any,
    collection: str,
    evidence_ids: list[str] | None,
    *,
    limit_per_id: int = 2,
) -> list[dict[str, Any]]:
    """Fetch recent-turn evidence by exact evidence_id as retrieval candidates."""
    if not evidence_ids:
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_ref in evidence_ids[:8]:
        ref = str(raw_ref or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        try:
            points, _ = await qdrant.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="evidence_id", match=MatchValue(value=ref))]
                ),
                limit=limit_per_id,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            continue
        for item in _points_to_items(list(points or [])):
            item_copy = dict(item)
            try:
                item_copy["score"] = max(float(item_copy.get("score") or 0.0), 1.0)
            except (TypeError, ValueError):
                item_copy["score"] = 1.0
            items.append(item_copy)
    return items


# ---------------------------------------------------------------------------
# Merge & dedupe
# ---------------------------------------------------------------------------

def _merge_candidates(
    *item_lists: list[dict[str, Any]],
    labels: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge multiple item lists, dedupe by evidence_id, track provenance."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    trace: dict[str, int] = {}
    channel_labels = labels or [f"ch{i}" for i in range(len(item_lists))]

    for idx, items in enumerate(item_lists):
        label = channel_labels[idx] if idx < len(channel_labels) else f"ch{idx}"
        added = 0
        for item in items:
            eid = str(item.get("evidence_id") or item.get("id") or id(item))
            if eid in seen:
                continue
            seen.add(eid)
            item_copy = dict(item)
            item_copy["_retrieval_channel"] = label
            merged.append(item_copy)
            added += 1
        trace[label] = added

    return merged, trace


# ---------------------------------------------------------------------------
# Intent-aware light rerank
# ---------------------------------------------------------------------------

_COMPACT_RE = re.compile(r"[\s，。！？、,.!?《》（）()·:：\-_]+")
_EXPLANATORY_QUERY_TERMS = (
    "关系",
    "影响",
    "启发",
    "认识",
    "理解",
    "为什么",
    "是什么",
    "是不是",
    "有关",
    "如何",
)
_ANALYSIS_SECTIONS = ("理论", "时评", "评论")


def _compact(text: str) -> str:
    return _COMPACT_RE.sub("", text or "")


def _lcs_len(a: str, b: str) -> int:
    a, b = _compact(a), _compact(b)
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ac in a:
        cur = [0]
        for j, bc in enumerate(b, 1):
            v = prev[j - 1] + 1 if ac == bc else 0
            cur.append(v)
            if v > best:
                best = v
        prev = cur
    return best


def _kw_overlap(terms: list[str], text: str) -> float:
    if not terms or not text:
        return 0.0
    return sum(1 for t in terms if t in text) / len(terms)


def _date_score(date_info: dict[str, Any], item: dict[str, Any]) -> float:
    if not date_info.get("has_explicit_date"):
        return 0.0
    hay = str(item.get("publish_time") or "") + " " + str(item.get("title") or "")
    s = 0.0
    y = date_info.get("year")
    if y and str(y) in hay:
        s += 2.0
    m = date_info.get("month")
    if m and f"{m}月" in hay:
        s += 3.0
    d = date_info.get("day")
    if d and f"{d}日" in hay:
        s += 2.0
    sm = date_info.get("since_month")
    if sm and f"{sm}月" in hay:
        s += 2.0
    return s


def _source_score(intent: QueryIntent, item: dict[str, Any]) -> float:
    if not intent.source_constraint:
        return 0.0
    isrc = str(item.get("source") or "")
    ititle = str(item.get("title") or "")
    for alias in intent.source_aliases:
        if alias in isrc or alias in ititle:
            return 3.0
    return 0.0


def _analysis_section_score(query: str, item: dict[str, Any], bonus: float) -> float:
    if bonus <= 0:
        return 0.0
    if not any(term in (query or "") for term in _EXPLANATORY_QUERY_TERMS):
        return 0.0
    section = str(item.get("section") or "")
    title = str(item.get("title") or "")
    if any(term in section for term in _ANALYSIS_SECTIONS):
        return bonus
    if "认识" in title or "理论" in title:
        return bonus
    return 0.0


def light_rerank_v2(
    query: str,
    items: list[dict[str, Any]],
    intent: QueryIntent,
    *,
    debug_top_k: int = 10,
    body_bonus: float = 0.8,
    entity_text_bonus: float = 0.5,
    diversity_max_per_source: int = 2,
    diversity_top_window: int = 10,
    diversity_score_tolerance: float = 2.0,
    analysis_section_bonus: float = 1.2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rerank ALL items by light rules; return full list in new order."""
    if not items:
        return [], []

    entities = intent.entities
    date_info = intent.date_constraint
    source_constrained = bool(intent.source_constraint)

    scored: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []

    for idx, item in enumerate(items):
        title = str(item.get("title") or "")
        chunk = str(item.get("summary") or item.get("text") or "")
        vec_score = float(item.get("score") or 0.0)

        lex_title = _kw_overlap(entities, title)
        lex_chunk = _kw_overlap(entities, chunk)
        lexical = lex_title * 0.6 + lex_chunk * 0.4

        lcs = _lcs_len(query, title)
        title_s = 0.0
        if title and title in query:
            title_s = 10.0
        elif lcs >= 8:
            title_s = float(lcs) * 0.8
        elif lcs >= 5:
            title_s = float(lcs) * 0.4

        date_s = _date_score(date_info, item)
        src_s = _source_score(intent, item)

        ent_bonus = 0.0
        for e in entities:
            if e in title:
                ent_bonus += 3.0 if len(e) >= 4 else 1.5

        length = len(chunk)
        len_pen = -3.0 if length < 30 else (-1.0 if length < 60 else 0.0)

        channel_bonus = 0.0
        ch = item.get("_retrieval_channel", "")
        if ch == "title_keyword":
            channel_bonus = 1.5
        elif ch == "chunk_keyword":
            channel_bonus = 0.5
        elif ch == "carryover_evidence":
            channel_bonus = 4.0

        body_b = body_bonus if item.get("chunk_type") == "body" else 0.0
        title_chunk = f"{title} {chunk}"
        text_overlap = sum(
            entity_text_bonus
            for e in entities
            if e and e not in title and e in title_chunk
        )
        analysis_s = _analysis_section_score(query, item, analysis_section_bonus)

        final = (
            vec_score * 10.0
            + lexical * 5.0
            + title_s
            + date_s
            + src_s
            + ent_bonus
            + len_pen
            + channel_bonus
            + body_b
            + text_overlap
            + analysis_s
        )

        reasons: list[str] = []
        if vec_score > 0.8:
            reasons.append("high_vector")
        if title_s >= 5.0:
            reasons.append("strong_title")
        if date_s > 0:
            reasons.append("date_match")
        if src_s > 0:
            reasons.append("source_match")
        if ent_bonus > 0:
            reasons.append("entity_in_title")
        if len_pen < 0:
            reasons.append("short_chunk")
        if ch == "carryover_evidence":
            reasons.append("carryover_evidence")
        elif channel_bonus > 0:
            reasons.append(f"kw_{ch}")
        if body_b > 0:
            reasons.append("body_chunk_bonus")
        if text_overlap > 0:
            reasons.append("entity_text_overlap")
        if analysis_s > 0:
            reasons.append("analysis_section_bonus")

        debug = {
            "vector_score": round(vec_score, 4),
            "lexical_score": round(lexical, 4),
            "title_score": round(title_s, 4),
            "date_score": round(date_s, 4),
            "source_score": round(src_s, 4),
            "entity_title_bonus": round(ent_bonus, 4),
            "length_penalty": round(len_pen, 4),
            "channel_bonus": round(channel_bonus, 4),
            "body_chunk_bonus": round(body_b, 4),
            "entity_text_overlap": round(text_overlap, 4),
            "analysis_section_bonus": round(analysis_s, 4),
            "final_score": round(final, 4),
            "rerank_reason": ", ".join(reasons) or "default",
            "channel": ch,
        }
        scored.append((final, -idx, item, debug))

    scored.sort(key=lambda x: x[0], reverse=True)
    if (
        not source_constrained
        and diversity_max_per_source > 0
        and diversity_top_window > 0
        and len(scored) > diversity_max_per_source
    ):
        window_size = min(len(scored), max(diversity_top_window, diversity_max_per_source))
        window = scored[:window_size]
        rest = scored[window_size:]
        promoted: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
        deferred: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
        source_counts: dict[str, int] = {}

        for pos, entry in enumerate(window):
            final_score, _neg_idx, item, debug = entry
            src = str(item.get("source") or "other")
            if source_counts.get(src, 0) < diversity_max_per_source:
                source_counts[src] = source_counts.get(src, 0) + 1
                promoted.append(entry)
                continue

            has_close_alternative = False
            for alt in window[pos + 1:]:
                alt_score, _alt_idx, alt_item, _alt_debug = alt
                alt_src = str(alt_item.get("source") or "other")
                if alt_src == src:
                    continue
                if source_counts.get(alt_src, 0) >= diversity_max_per_source:
                    continue
                if alt_score >= final_score - diversity_score_tolerance:
                    has_close_alternative = True
                    break

            if has_close_alternative:
                debug["source_diversity_deferred"] = True
                deferred.append(entry)
            else:
                source_counts[src] = source_counts.get(src, 0) + 1
                promoted.append(entry)

        scored = promoted + deferred + rest

    out: list[dict[str, Any]] = []
    dbg: list[dict[str, Any]] = []
    for rank, (final_score, _, item, debug) in enumerate(scored):
        c = dict(item)
        c["rerank_debug"] = debug
        c["rerank_score"] = round(final_score, 4)
        out.append(c)
        if rank < debug_top_k:
            dbg.append({
                "evidence_id": item.get("evidence_id") or f"news:{item.get('id')}",
                "title": item.get("title"),
                **debug,
            })
    return out, dbg


# ---------------------------------------------------------------------------
# No-answer evaluator (unchanged from 3.2-C)
# ---------------------------------------------------------------------------

_NA_VEC_THR = 0.55
_NA_LEX_THR = 0.05


def evaluate_no_answer(
    items: list[dict[str, Any]],
    intent: QueryIntent,
    rerank_debug: list[dict[str, Any]],
    *,
    fallback_used: bool = False,
) -> dict[str, Any]:
    if not items:
        return {
            "should_no_answer": True, "no_answer_score": 1.0,
            "top1_score": 0.0, "top5_avg_score": 0.0,
            "lexical_overlap_max": 0.0, "fallback_used": fallback_used,
            "no_answer_reason": "no_candidates",
        }

    t1 = float(items[0].get("score") or 0.0)
    t5 = [float(i.get("score") or 0.0) for i in items[:5]]
    t5avg = sum(t5) / len(t5) if t5 else 0.0

    lex_max = max((float(d.get("lexical_score") or 0.0) for d in rerank_debug[:5]), default=0.0)
    tit_max = max((float(d.get("title_score") or 0.0) for d in rerank_debug[:5]), default=0.0)
    date_hit = any(float(d.get("date_score") or 0.0) > 0 for d in rerank_debug[:5])
    src_hit = any(float(d.get("source_score") or 0.0) > 0 for d in rerank_debug[:5])

    conds = [t1 < _NA_VEC_THR, lex_max < _NA_LEX_THR, tit_max < 2.0, not date_hit and not src_hit]
    met = sum(conds)
    should = met >= 4 and not fallback_used and len(items) < 2

    reasons: list[str] = []
    if conds[0]: reasons.append(f"low_vec({t1:.3f})")
    if conds[1]: reasons.append(f"low_lex({lex_max:.3f})")
    if conds[2]: reasons.append("no_title")
    if conds[3]: reasons.append("no_date_src")

    return {
        "should_no_answer": should,
        "no_answer_score": round(met / 4.0, 4),
        "top1_score": round(t1, 4),
        "top5_avg_score": round(t5avg, 4),
        "lexical_overlap_max": round(lex_max, 4),
        "title_score_max": round(tit_max, 4),
        "fallback_used": fallback_used,
        "no_answer_reason": "; ".join(reasons) or "sufficient_evidence",
    }


# ---------------------------------------------------------------------------
# Collection route
# ---------------------------------------------------------------------------

def _semantic_collection_route(query: str) -> str:
    sources = [t for t in SOURCE_TRIGGERS if t in (query or "")]
    if any(s in ("新闻联播", "央视", "央视新闻") for s in sources):
        return "default"
    return "econ_finance_query" if is_econ_finance_query(query) else "default"


# ---------------------------------------------------------------------------
# Date hard-filter with fallback
# ---------------------------------------------------------------------------

def _apply_date_hard_filter(
    items: list[dict[str, Any]],
    date_info: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Returns (items, applied, fallback_used)."""
    if not date_info.get("has_explicit_date") or not items:
        return items, False, False
    year = date_info.get("year")
    month = date_info.get("month")
    since = date_info.get("since_month")
    if not year and not since:
        return items, False, False

    filtered: list[dict[str, Any]] = []
    for item in items:
        hay = str(item.get("publish_time") or "") + " " + str(item.get("title") or "")
        if year:
            if str(year) not in hay:
                continue
            if month:
                if f"{month}月" not in hay and f"{year}-{month:02d}" not in hay:
                    continue
        if since:
            if f"{since}月" not in hay:
                continue
        filtered.append(item)

    if len(filtered) >= 5:
        return filtered, True, False
    return items, False, True


# ---------------------------------------------------------------------------
# Main search entry point
# ---------------------------------------------------------------------------

async def search_news_rag_v2(
    query: str,
    limit: int = 50,
    *,
    vector_query: str | None = None,
    intent_query: str | None = None,
    collection_name: str | None = None,
    embedding_model: str | None = None,
    expected_dim: int | None = None,
    ranking: str | None = None,
    chunk_type_filter: str | None = None,
    expand_body_evidence: bool | None = None,
    body_chunks_per_parent: int | None = None,
    body_fallback_slots: int | None = None,
    query_router_enabled: bool | None = None,
    tool_name: str = "news_rag_search_v2",
    embedding_client_factory: Callable[[], Any] = get_v2_embedding_client,
    qdrant_factory: Callable[[], Any] = get_qdrant,
    carryover_evidence_ids: list[str] | None = None,
    multi_query: bool | None = None,
    qdrant_top_k: int | None = None,
    rerank_top_k: int = 10,
) -> dict[str, Any]:
    """Hybrid retrieval: dense + title keyword + chunk keyword."""
    t_start = time.perf_counter()

    final_limit = max(1, min(int(limit), 80))
    eff_qdrant_k = qdrant_top_k or DEFAULT_V2_TOP_K
    candidate_limit = max(final_limit, eff_qdrant_k)
    eff_collection = collection_name or DEFAULT_V2_COLLECTION
    eff_model = embedding_model or DEFAULT_V2_EMBEDDING_MODEL
    eff_dim = int(expected_dim or DEFAULT_V2_VECTOR_DIM)
    eff_ranking = ranking or settings.rag_ranking
    eff_chunk_filter = settings.rag_chunk_type_filter if chunk_type_filter is None else chunk_type_filter
    eff_expand_body = settings.rag_expand_body_evidence if expand_body_evidence is None else expand_body_evidence
    eff_body_chunks = settings.rag_body_chunks_per_parent if body_chunks_per_parent is None else body_chunks_per_parent
    cfg_body_slots = settings.rag_body_fallback_slots if body_fallback_slots is None else body_fallback_slots
    eff_router = settings.rag_query_router_enabled if query_router_enabled is None else query_router_enabled
    eff_multi = multi_query if multi_query is not None else RAG_V2_MULTI_QUERY
    eff_vector_query = vector_query or query
    eff_intent_query = intent_query or query
    eff_carryover_ids = [
        str(ref).strip()
        for ref in (carryover_evidence_ids or [])
        if str(ref or "").strip()
    ][:8]

    # ── Step 1: Intent parsing ──
    t_intent = time.perf_counter()
    intent = parse_query_intent(eff_intent_query)
    intent_ms = (time.perf_counter() - t_intent) * 1000

    # ── Step 2: Route ──
    route = route_rag_query(eff_intent_query, enabled=eff_router, default_body_fallback_slots=cfg_body_slots)
    eff_body_slots = max(0, int(route.body_fallback_slots or 0))
    source_values: list[str] = []
    if intent.source_constraint and route.query_type == "source_constrained":
        source_values = _source_filter_values(eff_intent_query)

    # ── Step 3: Embedding ──
    queries_to_embed = [eff_vector_query]
    if eff_multi and intent.entities and len(intent.entities) >= 2:
        entity_q = " ".join(intent.entities[:4])
        if entity_q != eff_vector_query:
            queries_to_embed.append(entity_q)

    all_vectors: list[list[float]] = []
    total_emb_ms = 0.0
    for q in queries_to_embed:
        vec, ms = await _embed_query_v2(
            q, embedding_model=eff_model, expected_dim=eff_dim,
            embedding_client_factory=embedding_client_factory,
        )
        all_vectors.append(vec)
        total_emb_ms += ms

    # ── Step 4: Dense search ──
    t_dense = time.perf_counter()
    qdrant = qdrant_factory()
    dense_items: list[dict[str, Any]] = []
    filter_fallback = False

    for vec in all_vectors:
        pts, fb = await _query_points(
            qdrant, vec, candidate_limit, eff_chunk_filter,
            eff_collection, source_values,
        )
        if fb:
            filter_fallback = True
        dense_items.extend(_points_to_items(pts))
    dense_ms = (time.perf_counter() - t_dense) * 1000

    # ── Step 5: Keyword search channels ──
    t_kw = time.perf_counter()
    title_kw_items: list[dict[str, Any]] = []
    chunk_kw_items: list[dict[str, Any]] = []
    carryover_items: list[dict[str, Any]] = []
    plan = intent.retrieval_plan

    kw_terms = intent.entities[:3]
    if not kw_terms and intent.source_constraint:
        kw_terms = intent.source_constraint[:2]

    if "title_keyword" in plan and kw_terms:
        title_kw_items = await _keyword_scroll(
            qdrant, eff_collection, "title", kw_terms,
            limit=_KEYWORD_SCROLL_LIMIT,
            chunk_type_filter="summary",
            source_values=source_values,
        )

    if "chunk_keyword" in plan and kw_terms:
        chunk_kw_items = await _keyword_scroll(
            qdrant, eff_collection, "chunk_text", kw_terms,
            limit=_KEYWORD_SCROLL_LIMIT,
            source_values=source_values,
        )
    carryover_items = await _evidence_id_scroll(qdrant, eff_collection, eff_carryover_ids)
    kw_ms = (time.perf_counter() - t_kw) * 1000

    # ── Step 6: Merge ──
    merged, channel_trace = _merge_candidates(
        carryover_items, dense_items, title_kw_items, chunk_kw_items,
        labels=["carryover_evidence", "dense", "title_keyword", "chunk_keyword"],
    )

    # ── Step 7: Quality / time filters (skip v1 hybrid rerank – it kills
    #    keyword items via 62% vector weight; light_rerank_v2 handles ordering) ──
    from harness.rag_ranking import normalize_publish_metadata
    merged = [normalize_publish_metadata(item) for item in merged]
    time_aware = False
    merged, lq_filtered = _filter_severe_low_quality(merged, final_limit)
    stale_filtered = 0
    if _has_recent_intent(eff_intent_query, route):
        merged, stale_filtered = _filter_stale_recent_items(merged, eff_intent_query, route)

    # ── Step 7b: Date hard-filter with fallback ──
    merged, date_applied, date_fb = _apply_date_hard_filter(merged, intent.date_constraint)

    # ── Step 8: Intent-aware light rerank ──
    t_rerank = time.perf_counter()
    reranked, rerank_debug = light_rerank_v2(
        query, merged, intent, debug_top_k=rerank_top_k,
    )
    rerank_ms = (time.perf_counter() - t_rerank) * 1000

    # ── Step 9: Source soft boost ──
    reranked = _apply_source_preference(query, reranked)

    # ── Step 10: Body fallback ──
    t_body = time.perf_counter()
    body_added = 0
    body_lq = 0
    body_stale = 0
    if eff_body_slots:
        body_pts, _ = await _query_points(
            qdrant, all_vectors[0], candidate_limit, "body",
            eff_collection, source_values,
        )
        body_items = _points_to_items(body_pts)
        body_items, _ = _rerank_items(query, body_items, eff_ranking, route)
        body_items, body_lq = _filter_severe_low_quality(body_items, eff_body_slots)
        if _has_recent_intent(eff_intent_query, route):
            body_items, body_stale = _filter_stale_recent_items(body_items, eff_intent_query, route)
        items, body_added = _with_body_fallback(reranked, body_items, final_limit, eff_body_slots)
    else:
        items = reranked[:final_limit]
    body_ms = (time.perf_counter() - t_body) * 1000

    # ── Step 11: No-answer check ──
    na_eval = evaluate_no_answer(
        items, intent, rerank_debug,
        fallback_used=filter_fallback or date_fb,
    )

    total_ms = (time.perf_counter() - t_start) * 1000

    # ── Build result ──
    final_items = _dedupe_items(items)[:final_limit]
    result: dict[str, Any] = {
        "tool": tool_name,
        "items": final_items,
        "rag_route": route.to_dict(),
        "ranking": eff_ranking,
        "candidate_limit": candidate_limit,
        "chunk_type_filter": eff_chunk_filter,
        "chunk_type_filter_fallback_used": filter_fallback,
        "body_fallback_slots": eff_body_slots,
        "body_fallback_used": body_added,
        "time_aware_ranking": time_aware,
        "low_quality_filtered": lq_filtered + body_lq,
        "stale_time_filtered": stale_filtered + body_stale,
        "collection_name": eff_collection,
        "collection_route": _semantic_collection_route(eff_intent_query),
        "index_version": "v2_unified",
        "embedding_model": eff_model,
        "vector_dim": eff_dim,
        "query_inputs": {
            "query": query,
            "vector_query": eff_vector_query,
            "intent_query": eff_intent_query,
        },
        "carryover_evidence_ids": eff_carryover_ids,
        # 3.2-D debug
        "intent": intent.to_dict(),
        "query_debug": intent.to_dict(),
        "retrieval_channels": channel_trace,
        "rerank_debug": rerank_debug,
        "no_answer_eval": na_eval,
        "date_filter_applied": date_applied,
        "date_fallback_used": date_fb,
        "latency": {
            "intent_ms": round(intent_ms, 2),
            "embedding_ms": round(total_emb_ms, 2),
            "dense_ms": round(dense_ms, 2),
            "keyword_ms": round(kw_ms, 2),
            "rerank_ms": round(rerank_ms, 2),
            "body_ms": round(body_ms, 2),
            "total_ms": round(total_ms, 2),
            "multi_query_enabled": eff_multi,
            "query_count": len(queries_to_embed),
        },
    }
    result["evidence_ids"] = [
        eid for item in final_items if (eid := item.get("evidence_id"))
    ]

    if eff_expand_body:
        await _attach_body_evidence(qdrant, result, eff_body_chunks, eff_collection)

    return result


async def search_news_v2(
    query: str,
    top_k: int = 5,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility entry point for v2 smoke checks."""
    limit = kwargs.pop("limit", top_k)
    result = await search_news_rag_v2(query, limit=limit, **kwargs)
    result.setdefault("route", result.get("collection_route") or "default")
    latency = result.get("latency")
    if isinstance(latency, dict):
        result.setdefault("latency_ms", latency.get("total_ms"))
    return result


__all__ = [
    "DEFAULT_V2_COLLECTION",
    "DEFAULT_V2_EMBEDDING_MODEL",
    "DEFAULT_V2_VECTOR_DIM",
    "evaluate_no_answer",
    "get_v2_embedding_client",
    "light_rerank_v2",
    "search_news_v2",
    "search_news_rag_v2",
]
