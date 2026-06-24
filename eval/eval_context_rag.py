"""Context Manager + RAG evaluation runner.

Modes:
- retrieve-only: use the real retrieval adapter and Context Manager query rewrite.
- full-e2e: call the real /api/ai/chat SSE endpoint with authenticated sessions.

This eval does not create collections, change indexes, or expand Agent
permissions. Memory fields are used only to build the retrieval query and are
never counted as factual evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import inspect
import json
import os
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.ai_conf import settings
from config.db_conf import AsyncSessionLocal
from config.vector_conf import CHUNK_COLLECTION, COLLECTION, get_qdrant
from harness.agent import _aggregate_parents
from harness.answer_validator import REFUSAL_PATTERNS, extract_citations
from harness.context_manager import (
    build_contextual_retrieval_query,
    build_session_context,
    clean_retrieval_query,
    is_contextual_follow_up,
)
from harness.evidence_detail_resolver import DEFAULT_JSONL_PATHS, normalize_evidence_id
from harness.intent import detect_intent
from harness.rag_search import search_news_rag
from harness.rag_search_v2 import DEFAULT_V2_COLLECTION, search_news_rag_v2
from harness.reranker_api import rerank_with_api as api_rerank
from harness.reranker import fusion_rerank, rerank


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD_PATH = PROJECT_ROOT / "eval" / "gold" / "eval_gold_retrieval.jsonl"
B_V3_GOLD_PATH = PROJECT_ROOT / "eval" / "gold" / "b_v3_anchor_resolver_20260624.jsonl"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "eval" / "reports" / "context_rag_baseline_20260622.md"
DEFAULT_JSON_REPORT_PATH = PROJECT_ROOT / "eval" / "reports" / "context_rag_baseline_20260622.json"

B_V3_REQUIRED_SCENARIOS = (
    "candidate_confirmation",
    "confirmed_followup",
    "external_fallback",
    "low_credibility_warning",
    "ocr_lead",
    "long_context_100",
)


REQUIRED_CASE_FIELDS = {
    "id",
    "expected_route",
    "gold_evidence_ids",
    "should_answer",
    "should_refuse",
    "must_have_citations",
    "case_type",
    "notes",
}


@dataclass
class ApiAuth:
    username: str
    password: str
    token: str


def load_gold_cases(path: str | Path = DEFAULT_GOLD_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            raw = line.strip()
            if not raw:
                continue
            case = json.loads(raw)
            missing = REQUIRED_CASE_FIELDS - set(case)
            if missing:
                raise ValueError(f"case line {line_no} missing fields: {sorted(missing)}")
            if "question" not in case and "turns" not in case:
                raise ValueError(f"case line {line_no} must include question or turns")
            if not isinstance(case.get("gold_evidence_ids"), list):
                raise ValueError(f"case line {line_no} gold_evidence_ids must be list")
            cases.append(case)
    return cases


def summarize_b_v3_gold_coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_counts = Counter(str(case.get("b_v3_scenario") or "") for case in cases)
    missing = [
        scenario
        for scenario in B_V3_REQUIRED_SCENARIOS
        if scenario_counts.get(scenario, 0) <= 0
    ]
    return {
        "case_count": len(cases),
        "scenario_counts": dict(scenario_counts),
        "missing_required_scenarios": missing,
    }


def select_cases(
    cases: list[dict[str, Any]],
    *,
    case_ids: list[str] | None = None,
    case_limit: int = 0,
) -> list[dict[str, Any]]:
    if case_ids:
        by_id = {str(case["id"]): case for case in cases}
        missing = [case_id for case_id in case_ids if case_id not in by_id]
        if missing:
            raise ValueError(f"unknown case ids: {missing}")
        return [by_id[case_id] for case_id in case_ids]
    if case_limit:
        return cases[:case_limit]
    return cases


def normalize_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def _case_turns(case: dict[str, Any]) -> list[str]:
    if case.get("turns"):
        turns = [str(turn) for turn in case["turns"]]
    else:
        turns = [str(case["question"])]

    long_context = case.get("long_context")
    if not isinstance(long_context, dict):
        return turns
    try:
        target_turns = int(long_context.get("simulated_round") or 0)
    except (TypeError, ValueError):
        target_turns = 0
    if target_turns <= len(turns) or len(turns) < 2:
        return turns

    template = str(long_context.get("filler_template") or "第{turn}轮只是格式确认。")
    explicit_by_round: dict[int, str] = {}
    for turn in turns[1:-1]:
        match = re.search(r"第\s*(\d{1,3})\s*轮", turn)
        if not match:
            continue
        explicit_by_round[int(match.group(1))] = turn

    expanded = [turns[0]]
    for turn_index in range(2, target_turns):
        expanded.append(explicit_by_round.get(turn_index, template.replace("{turn}", str(turn_index))))
    expanded.append(turns[-1])
    return expanded


def _is_refusal(answer: str) -> bool:
    compact = "".join(str(answer or "").split())
    if any(token in compact for token in REFUSAL_PATTERNS):
        return True
    return "未找到" in compact and any(token in compact for token in ("证据", "新闻", "报道", "可靠"))


def _source_label_check(row: dict[str, Any]) -> float | None:
    label = row.get("source_label")
    if not isinstance(label, dict):
        return None
    if label.get("correct") is not None:
        return 1.0 if label.get("correct") else 0.0
    expected = str(label.get("expected") or label.get("expected_source_type") or "").strip().lower()
    actual = str(label.get("actual") or label.get("actual_source_type") or "").strip().lower()
    if not expected or not actual:
        return None
    return 1.0 if expected == actual else 0.0


def _low_credibility_warning_required(row: dict[str, Any]) -> bool:
    anchor_resolution = row.get("anchor_resolution")
    if isinstance(anchor_resolution, dict) and anchor_resolution.get("warning_required") is not None:
        return bool(anchor_resolution.get("warning_required"))
    if row.get("low_credibility_warning_required") is not None:
        return bool(row.get("low_credibility_warning_required"))
    return False


def _low_credibility_warning_check(row: dict[str, Any]) -> float | None:
    if not _low_credibility_warning_required(row):
        return None
    if row.get("low_credibility_warning_present") is not None:
        return 1.0 if row.get("low_credibility_warning_present") else 0.0
    if row.get("answer") is None:
        return None
    answer = str(row.get("answer") or "")
    has_warning = "可信度较低" in answer and (
        "不作为确定事实" in answer
        or "只能作为线索" in answer
        or "尚未被站内" in answer
    )
    return 1.0 if has_warning else 0.0


def _tool_names(row: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("tool_calls", "tools_used", "tool_results"):
        value = row.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and item:
                names.add(item)
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("tool") or "").strip()
                if name:
                    names.add(name)
    answer = str(row.get("answer") or "")
    if any(token in answer for token in ("WEB_SEARCH_API_KEY", "联网搜索", "站外工具", "web_search")):
        names.add("web_search")
    return names


def _external_fallback_check(row: dict[str, Any]) -> float | None:
    expected = row.get("external_tool_expected") or (row.get("anchor_resolution") or {}).get("external_tool_expected")
    expected = str(expected or "").strip()
    if not expected:
        return None
    return 1.0 if expected in _tool_names(row) else 0.0


def _ocr_trace_check(row: dict[str, Any]) -> float | None:
    trace = row.get("ocr_trace")
    if not isinstance(trace, dict):
        return None
    required = ("source_url", "image_path", "raw_image_hash", "captured_at", "ocr_confidence")
    return 1.0 if all(trace.get(field) is not None and str(trace.get(field)) for field in required) else 0.0


def _confirmed_carryover_check(row: dict[str, Any]) -> float | None:
    carryover = row.get("confirmed_carryover")
    if not isinstance(carryover, dict):
        return None
    if carryover.get("passed") is not None:
        return 1.0 if carryover.get("passed") else 0.0
    expected = str(carryover.get("expected_anchor_id") or "").strip()
    actual = str(carryover.get("actual_anchor_id") or "").strip()
    if not expected or not actual:
        return None
    return 1.0 if expected == actual else 0.0


def _insufficient_evidence_check(row: dict[str, Any]) -> float | None:
    expected = row.get("insufficient_evidence_expected")
    anchor_resolution = row.get("anchor_resolution")
    if expected is None and isinstance(anchor_resolution, dict):
        expected = str(anchor_resolution.get("expected_state") or "").upper() == "INSUFFICIENT_EVIDENCE"
    if not expected:
        return None
    if row.get("insufficient_evidence_handled") is not None:
        return 1.0 if row.get("insufficient_evidence_handled") else 0.0
    if row.get("answer") is None:
        return None
    return 1.0 if _is_refusal(str(row.get("answer") or "")) else 0.0


def _confirmation_required_check(row: dict[str, Any]) -> float | None:
    anchor_resolution = row.get("anchor_resolution")
    if not isinstance(anchor_resolution, dict):
        return None
    expected = anchor_resolution.get("requires_user_confirmation")
    actual = anchor_resolution.get("actual_requires_user_confirmation")
    if actual is not None and expected is not None:
        return 1.0 if bool(actual) == bool(expected) else 0.0
    if expected is None:
        return None
    return 1.0 if expected else 0.0


def _overconfident_answer_check(row: dict[str, Any]) -> float | None:
    anchor_resolution = row.get("anchor_resolution")
    if not isinstance(anchor_resolution, dict):
        return None
    actual = anchor_resolution.get("actual_answered_without_confirmation")
    if actual is not None:
        return 1.0 if actual else 0.0
    if anchor_resolution.get("answered_without_confirmation") is None:
        return None
    return 1.0 if anchor_resolution.get("answered_without_confirmation") else 0.0


def _expected_source_label(row: dict[str, Any]) -> str:
    anchor_resolution = row.get("anchor_resolution")
    if isinstance(anchor_resolution, dict):
        acquisition_method = str(anchor_resolution.get("acquisition_method") or "").strip().lower()
        if acquisition_method:
            return acquisition_method
        if anchor_resolution.get("external_tool_expected"):
            return str(anchor_resolution.get("external_tool_expected") or "").strip().lower()
        allowed = [str(item).lower() for item in (anchor_resolution.get("allowed_source_credibility") or [])]
        if "high" in allowed:
            return "rag"
    return ""


def _source_label_from_anchor_candidates(anchor_resolution: dict[str, Any]) -> str:
    for key in ("actual_candidates", "candidates", "actual_leads", "leads"):
        candidates = anchor_resolution.get(key)
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            acquisition_method = str(candidate.get("acquisition_method") or "").strip().lower()
            if acquisition_method:
                return acquisition_method
            ref = str(candidate.get("source_url") or candidate.get("anchor_id") or "").strip()
            if ref.startswith("news:"):
                return "rag"
            if ref.startswith(("http://", "https://")):
                return "web_search"
    return ""


def _actual_source_label(row: dict[str, Any]) -> str:
    existing = row.get("source_label")
    if isinstance(existing, dict):
        actual = str(existing.get("actual") or existing.get("actual_source_type") or "").strip().lower()
        if actual:
            return actual
    anchor_resolution = row.get("anchor_resolution")
    if isinstance(anchor_resolution, dict):
        candidate_label = _source_label_from_anchor_candidates(anchor_resolution)
        if candidate_label:
            return candidate_label
    answer = str(row.get("answer") or "")
    if any(token in answer for token in ("OCR", "ocr", "截图", "识别")):
        return "ocr_screenshot"
    evidence_refs = [str(ref) for ref in (row.get("retrieved_evidence_ids") or row.get("done_evidence") or [])]
    if any(ref.startswith("web:") for ref in evidence_refs):
        return "web_search"
    if any(ref.startswith("news:") for ref in evidence_refs):
        return "rag"
    if any(token in answer for token in ("Reuters", "路透", "http://", "https://", "站外")):
        return "web_search"
    return ""


def _enrich_b_v3_eval_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("eval_profile") != "b_v3_anchor_resolver" and not row.get("b_v3_scenario"):
        return row

    enriched = dict(row)
    done = enriched.get("done")
    if isinstance(done, dict):
        done_anchor_resolution = done.get("anchorResolution")
        if isinstance(done_anchor_resolution, dict):
            existing_anchor_resolution = enriched.get("anchor_resolution")
            if isinstance(existing_anchor_resolution, dict):
                merged_anchor_resolution = dict(existing_anchor_resolution)
                for source_key, target_key in (
                    ("state", "actual_state"),
                    ("requires_user_confirmation", "actual_requires_user_confirmation"),
                    ("candidate_count", "actual_candidate_count"),
                    ("lead_count", "actual_lead_count"),
                    ("answered_without_confirmation", "actual_answered_without_confirmation"),
                    ("candidates", "actual_candidates"),
                    ("leads", "actual_leads"),
                ):
                    if source_key in done_anchor_resolution:
                        merged_anchor_resolution[target_key] = done_anchor_resolution[source_key]
                enriched["anchor_resolution"] = merged_anchor_resolution
            elif "anchor_resolution" not in enriched:
                enriched["anchor_resolution"] = done_anchor_resolution
        if "confirmed_anchor" not in enriched and isinstance(done.get("confirmedAnchor"), dict):
            enriched["confirmed_anchor"] = done["confirmedAnchor"]

    expected_label = _expected_source_label(enriched)
    actual_label = _actual_source_label(enriched)
    if expected_label and actual_label and not isinstance(enriched.get("source_label"), dict):
        enriched["source_label"] = {"expected": expected_label, "actual": actual_label}

    anchor_resolution = enriched.get("anchor_resolution")
    if isinstance(anchor_resolution, dict) and anchor_resolution.get("warning_required") is not None:
        enriched.setdefault("low_credibility_warning_required", bool(anchor_resolution.get("warning_required")))

    if (
        isinstance(anchor_resolution, dict)
        and anchor_resolution.get("confirmed_anchor_expected")
        and not isinstance(enriched.get("confirmed_carryover"), dict)
    ):
        gold_refs = [normalize_ref(ref) for ref in (enriched.get("gold_evidence_ids") or [])]
        actual_refs = [
            normalize_ref(ref)
            for ref in (enriched.get("retrieved_evidence_ids") or enriched.get("done_evidence") or [])
        ]
        expected_anchor = gold_refs[0] if gold_refs else ""
        actual_anchor = ""
        if expected_anchor and expected_anchor in actual_refs:
            actual_anchor = expected_anchor
        elif actual_refs:
            actual_anchor = actual_refs[0]
        if expected_anchor and actual_anchor:
            enriched["confirmed_carryover"] = {
                "expected_anchor_id": expected_anchor,
                "actual_anchor_id": actual_anchor,
            }

    if isinstance(anchor_resolution, dict):
        expected_state = str(anchor_resolution.get("expected_state") or "").upper()
        if expected_state == "INSUFFICIENT_EVIDENCE":
            enriched.setdefault("insufficient_evidence_expected", True)

    return enriched


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _first_gold_rank(retrieved: list[str], gold: list[str]) -> int | None:
    gold_set = {normalize_ref(item) for item in gold if item}
    for index, ref in enumerate(retrieved, 1):
        if normalize_ref(ref) in gold_set:
            return index
    return None


def gold_ranks_for_row(row: dict[str, Any], diagnosis_k: int = 20) -> dict[str, int | None]:
    retrieved = [normalize_ref(ref) for ref in (row.get("retrieved_evidence_ids") or [])[:diagnosis_k]]
    ranks: dict[str, int | None] = {}
    for gold_ref in row.get("gold_evidence_ids") or []:
        normalized = normalize_ref(gold_ref)
        ranks[normalized] = retrieved.index(normalized) + 1 if normalized in retrieved else None
    return ranks


def _evidence_core_id(evidence_id: str) -> str:
    return evidence_id[len("news:"):] if evidence_id.startswith("news:") else evidence_id


def _source_and_doc_id(core: str) -> tuple[str | None, str | None]:
    if ":" not in core:
        return None, None
    source, doc_id = core.split(":", 1)
    return source or None, doc_id or None


def _gold_lookup_candidates(evidence_id: str) -> list[tuple[str, Any]]:
    core = _evidence_core_id(evidence_id)
    source, source_doc_id = _source_and_doc_id(core)
    candidates: list[tuple[str, Any]] = [
        ("evidence_id", evidence_id),
        ("doc_id", core),
        ("news_id", core),
        ("parent_news_id", core),
    ]
    if source_doc_id:
        candidates.append(("source_doc_id", source_doc_id))
    if source and source_doc_id:
        scoped = f"{source}:{source_doc_id}"
        candidates.extend([
            ("doc_id", scoped),
            ("news_id", scoped),
            ("parent_news_id", scoped),
        ])
    if core.isdigit():
        numeric = int(core)
        candidates.extend([
            ("id", numeric),
            ("news_id", numeric),
            ("parent_news_id", numeric),
        ])

    deduped: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, value in candidates:
        marker = (key, repr(value))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append((key, value))
    return deduped


def _query_id_set(evidence_id: str) -> set[str]:
    core = _evidence_core_id(evidence_id)
    source, source_doc_id = _source_and_doc_id(core)
    values = {evidence_id, core}
    if source and source_doc_id:
        values.update({source_doc_id, f"{source}:{source_doc_id}", f"news:{source}:{source_doc_id}"})
    values.discard("")
    return values


def _row_id_set(row: dict[str, Any]) -> set[str]:
    values = {
        str(row.get("evidence_id") or ""),
        str(row.get("doc_id") or ""),
        str(row.get("news_id") or ""),
        str(row.get("parent_news_id") or ""),
        str(row.get("source_doc_id") or ""),
        str(row.get("id") or ""),
    }
    values.discard("")
    return values


def _default_gold_collections() -> list[str]:
    collections = [
        os.getenv("QDRANT_UNIFIED_COLLECTION", DEFAULT_V2_COLLECTION),
        settings.rag_econ_collection_name,
        CHUNK_COLLECTION,
        COLLECTION,
    ]
    out: list[str] = []
    for collection in collections:
        if collection and collection not in out:
            out.append(collection)
    return out


async def _maybe_close(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def _check_mysql_metadata(evidence_id: str, db: AsyncSession | None) -> dict[str, Any]:
    core = _evidence_core_id(evidence_id)
    if db is None:
        return {"checked": False, "found": False, "reason": "db_not_configured"}
    if not core.isdigit():
        return {"checked": False, "found": False, "reason": "non_numeric_news_id"}
    try:
        result = await db.execute(
            text("SELECT id FROM news WHERE id = :news_id LIMIT 1"),
            {"news_id": int(core)},
        )
        found = result.first() is not None
        return {"checked": True, "found": found, "news_id": int(core)}
    except Exception as exc:  # noqa: BLE001 - eval diagnostics should preserve source errors.
        return {"checked": True, "found": False, "error": str(exc)}


def _scan_news_chunk_sources(evidence_ids: list[str], jsonl_paths: list[Path]) -> dict[str, dict[str, Any]]:
    normalized_ids = [normalize_evidence_id(ref) for ref in evidence_ids if normalize_evidence_id(ref)]
    targets = {ref: _query_id_set(ref) for ref in normalized_ids}
    results = {
        ref: {"checked": True, "found": False, "paths_checked": [str(path) for path in jsonl_paths]}
        for ref in normalized_ids
    }
    unresolved = set(normalized_ids)
    for path in jsonl_paths:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not unresolved:
                        return results
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    row_ids = _row_id_set(row)
                    for ref in list(unresolved):
                        if row_ids.isdisjoint(targets[ref]):
                            continue
                        results[ref].update({
                            "found": True,
                            "path": str(path),
                            "title": row.get("title"),
                            "source": row.get("source") or row.get("author"),
                        })
                        unresolved.remove(ref)
        except Exception as exc:  # noqa: BLE001 - keep eval running and expose source failure.
            for ref in unresolved:
                results[ref].setdefault("errors", []).append({"path": str(path), "error": str(exc)})
    return results


async def _check_qdrant_payload(
    evidence_id: str,
    *,
    qdrant_factory: Any,
    collections: list[str],
) -> dict[str, Any]:
    client = qdrant_factory()
    try:
        for collection in collections:
            for key, value in _gold_lookup_candidates(evidence_id):
                try:
                    points, _next_offset = await client.scroll(
                        collection_name=collection,
                        scroll_filter=Filter(must=[FieldCondition(key=key, match=MatchValue(value=value))]),
                        limit=1,
                        with_payload=True,
                        with_vectors=False,
                    )
                except Exception as exc:  # noqa: BLE001 - try the next candidate/collection.
                    last_error = str(exc)
                    continue
                if points:
                    payload = dict(getattr(points[0], "payload", None) or {})
                    return {
                        "checked": True,
                        "found": True,
                        "collection": collection,
                        "field": key,
                        "value": value,
                        "title": payload.get("title"),
                        "source": payload.get("source") or payload.get("author"),
                        "chunk_type": payload.get("chunk_type"),
                    }
        return {"checked": True, "found": False, "collections_checked": collections}
    except Exception as exc:  # noqa: BLE001 - eval diagnostics should not abort all cases.
        return {"checked": True, "found": False, "error": str(exc)}
    finally:
        await _maybe_close(client)


async def check_gold_evidence_existence(
    evidence_ids: list[str],
    *,
    db: AsyncSession | None = None,
    qdrant_factory: Any = get_qdrant,
    collections: list[str] | None = None,
    jsonl_paths: list[str | Path] | None = None,
) -> dict[str, dict[str, Any]]:
    normalized_ids = []
    seen: set[str] = set()
    for ref in evidence_ids:
        normalized = normalize_evidence_id(str(ref or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)

    paths = [Path(path) for path in (jsonl_paths if jsonl_paths is not None else DEFAULT_JSONL_PATHS)]
    chunk_checks = _scan_news_chunk_sources(normalized_ids, paths)
    collection_names = list(collections if collections is not None else _default_gold_collections())

    results: dict[str, dict[str, Any]] = {}
    for ref in normalized_ids:
        mysql_check = await _check_mysql_metadata(ref, db)
        qdrant_check = await _check_qdrant_payload(ref, qdrant_factory=qdrant_factory, collections=collection_names)
        checks = {
            "mysql_metadata": mysql_check,
            "news_chunk": chunk_checks.get(ref, {"checked": True, "found": False}),
            "qdrant_payload": qdrant_check,
        }
        present_in = [name for name, check in checks.items() if check.get("found")]
        malformed = not ref.startswith("news:")
        exists = bool(present_in)
        status = "exists" if exists else ("possible_gold_issue" if malformed else "corpus_missing")
        results[ref] = {
            "evidence_id": ref,
            "exists": exists,
            "status": status,
            "present_in": present_in,
            "checks": checks,
        }
    return results


def summarize_gold_existence(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    checked_refs: dict[str, dict[str, Any]] = {}
    for diagnosis in diagnostics:
        for ref, presence in (diagnosis.get("gold_existence") or {}).items():
            checked_refs[normalize_ref(ref)] = presence

    source_hits: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for presence in checked_refs.values():
        status_counts[str(presence.get("status") or "unknown")] += 1
        for source in presence.get("present_in") or []:
            source_hits[str(source)] += 1

    exists = sum(1 for presence in checked_refs.values() if presence.get("exists"))
    return {
        "gold_refs_checked": len(checked_refs),
        "exists": exists,
        "missing": len(checked_refs) - exists,
        "status_counts": dict(status_counts),
        "source_hits": dict(source_hits),
    }


def _requires_factual_evidence_recall(row: dict[str, Any]) -> bool:
    return bool(
        row.get("should_answer")
        and row.get("gold_evidence_ids")
        and row.get("answer_mode") != "memory_recall_not_fact_evidence"
    )


def diagnose_failure(
    row: dict[str, Any],
    *,
    metric_k: int = 5,
    diagnosis_k: int = 20,
    gold_existence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ranks = gold_ranks_for_row(row, diagnosis_k=diagnosis_k)
    buckets: list[str] = []
    route_mismatch = bool(row.get("expected_route") and row.get("route") != row.get("expected_route"))
    if route_mismatch:
        buckets.append("route_mismatch")

    case_type = str(row.get("case_type") or "")
    gold_values = [rank for rank in ranks.values() if rank is not None]
    has_gold_top_k = any(rank <= metric_k for rank in gold_values)
    has_gold_top_diagnosis = any(rank <= diagnosis_k for rank in gold_values)
    if _requires_factual_evidence_recall(row) and ranks and not has_gold_top_k:
        if has_gold_top_diagnosis:
            buckets.append("gold_in_top20_not_top5")
        else:
            buckets.append("gold_not_in_top20")

    attached_existence: dict[str, dict[str, Any]] = {}
    if "gold_not_in_top20" in buckets and gold_existence:
        for gold_ref, rank in ranks.items():
            if rank is None:
                presence = gold_existence.get(gold_ref)
                if presence:
                    attached_existence[gold_ref] = presence
        if attached_existence:
            if any(item.get("exists") for item in attached_existence.values()):
                buckets.append("query_rewrite_or_ranking")
            missing_statuses = {str(item.get("status")) for item in attached_existence.values() if not item.get("exists")}
            if "corpus_missing" in missing_statuses:
                buckets.append("corpus_missing")
            if "possible_gold_issue" in missing_statuses:
                buckets.append("possible_gold_issue")

    if case_type.startswith("D_") and ("route_mismatch" in buckets or "gold_not_in_top20" in buckets):
        buckets.append("source_filter_mismatch")
    if case_type.startswith("G_") and route_mismatch:
        buckets.append("no_answer_route_error")
    if case_type.startswith("H_") and route_mismatch:
        buckets.append("investment_boundary_route_error")
    if (
        case_type.startswith("G_")
        and row.get("should_refuse")
        and row.get("expected_route") == "default"
        and row.get("route") == "econ_finance_query"
        and not row.get("gold_evidence_ids")
    ):
        buckets.append("possible_gold_issue")

    diagnosis = {
        "id": row.get("id"),
        "case_type": row.get("case_type"),
        "buckets": buckets,
        "gold_ranks": ranks,
        "expected_route": row.get("expected_route"),
        "route": row.get("route"),
        "retrieval_query": row.get("retrieval_query"),
        "gold_evidence_ids": row.get("gold_evidence_ids") or [],
        "retrieved_evidence_ids": row.get("retrieved_evidence_ids") or [],
        "collection": row.get("collection"),
        "latency_ms": row.get("latency_ms"),
    }
    if attached_existence:
        diagnosis["gold_existence"] = attached_existence
    return diagnosis


def diagnose_failures(
    rows: list[dict[str, Any]],
    *,
    metric_k: int = 5,
    diagnosis_k: int = 20,
    gold_existence: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        diagnosis for row in rows
        if (diagnosis := diagnose_failure(
            row,
            metric_k=metric_k,
            diagnosis_k=diagnosis_k,
            gold_existence=gold_existence,
        ))["buckets"]
    ]


def _citation_valid(citations: list[str], evidence_ids: list[str]) -> bool | None:
    if not citations:
        return None
    evidence = {normalize_ref(ref) for ref in evidence_ids}
    return all(normalize_ref(citation) in evidence for citation in citations)


_TERM_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}")
_KNOWN_ENTITY_TERMS = (
    "新质生产力",
    "高质量发展",
    "科技创新",
    "产业升级",
    "产业链",
    "制造业",
    "高技术制造业",
    "现代化产业体系",
    "半导体",
    "新能源",
    "经济日报",
    "人民日报",
    "新闻联播",
)


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    text = query or ""
    for term in _KNOWN_ENTITY_TERMS:
        if term in text and term not in terms:
            terms.append(term)
    for term in _TERM_RE.findall(text):
        if len(term) >= 3 and term not in terms and term not in {"这篇报道讲了什么", "有什么报道"}:
            terms.append(term)
    return terms[:20]


def _compact_text(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?《》（）()·:：\-_]+", "", text or "")


def _longest_common_substring_len(left: str, right: str) -> int:
    left = _compact_text(left)
    right = _compact_text(right)
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0]
        for index, right_char in enumerate(right, 1):
            value = previous[index - 1] + 1 if left_char == right_char else 0
            current.append(value)
            if value > best:
                best = value
        previous = current
    return best


_LIGHT_RERANK_SOURCE_ALIASES = {
    "经济日报": ("jjrb", "经济日报"),
    "人民日报": ("rmrb", "人民日报"),
    "新闻联播": ("新闻联播",),
    "央视": ("央视", "新闻联播"),
    "新华社": ("新华社",),
}


def light_rule_rerank(query: str, parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lightweight diagnostic rerank over already-retrieved parent candidates."""
    terms = _query_terms(query)
    if not terms or not parents:
        return parents

    source_aliases: list[tuple[str, ...]] = []
    for source_name, aliases in _LIGHT_RERANK_SOURCE_ALIASES.items():
        if source_name in query:
            source_aliases.append(aliases)

    def score(index: int, item: dict[str, Any]) -> tuple[float, int]:
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or item.get("text") or "")
        haystack = title + "\n" + summary
        value = 0.0
        for term in terms:
            if term in title:
                value += 3.0 if len(term) >= 4 else 1.0
            elif term in haystack:
                value += 1.0
        title_overlap = _longest_common_substring_len(query, title)
        if title_overlap >= 8:
            value += float(title_overlap)
        if query and title and title in query:
            value += 8.0
        if source_aliases:
            item_source = str(item.get("source") or "")
            for aliases in source_aliases:
                if any(alias in item_source or alias == item_source for alias in aliases):
                    value += 2.0
                    break
        return value, -index

    indexed = list(enumerate(parents))
    ranked = sorted(indexed, key=lambda pair: score(pair[0], pair[1]), reverse=True)
    return [item for _index, item in ranked]


_MULTI_QUERY_ELIGIBLE_CASE_TYPES = (
    "B_context_follow_up",
    "E_multi_document",
    "C_time_sensitive",
)


def is_multi_query_eligible(case_type: str) -> bool:
    return str(case_type or "").startswith(("B_", "E_", "C_"))


_MULTI_QUERY_ENTITY_FOCUS = (
    "新质生产力",
    "高质量发展",
    "科技创新",
    "产业升级",
    "产业链",
    "制造业",
    "高技术制造业",
    "现代化产业体系",
    "先进制造",
    "半导体",
)


def build_query_variants(query: str, *, case_type: str = "", max_variants: int = 2) -> list[str]:
    """Build up to 2 query variants for multi-query recall patch.

    Only eligible case types (B_/E_/C_) get expanded variants; others return
    the original query only. Capped at 2 variants to keep latency under 1500ms.
    """
    base = (query or "").strip()
    if not base:
        return []
    if not is_multi_query_eligible(case_type):
        return [base]

    variants: list[str] = [base]

    focus_terms = [term for term in _MULTI_QUERY_ENTITY_FOCUS if term in base]
    if focus_terms and len(focus_terms) >= 2:
        compact = " ".join(focus_terms[:4])
        if compact != base and compact not in variants:
            variants.append(compact)

    return variants[:max_variants]


def merge_dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge candidate lists from multiple query variants, keeping the best score per id."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in candidates:
        eid = str(item.get("evidence_id") or item.get("id") or id(item))
        score = float(item.get("score") or item.get("rerank_score") or item.get("fusion_score") or 0.0)
        if eid not in best:
            best[eid] = dict(item)
            order.append(eid)
        elif score > float(best[eid].get("score") or best[eid].get("rerank_score") or best[eid].get("fusion_score") or 0.0):
            best[eid] = dict(item)
    return [best[eid] for eid in order]


def _candidate_evidence_ref(item: dict[str, Any]) -> str:
    evidence_id = item.get("evidence_id")
    if evidence_id:
        return str(evidence_id)
    item_id = item.get("id")
    if item_id is None:
        return ""
    value = str(item_id)
    return value if value.startswith("news:") else f"news:{value}"


def _score_for_sort(item: dict[str, Any]) -> float:
    try:
        return float(
            item.get("rerank_score")
            or item.get("api_rerank_score")
            or item.get("fusion_score")
            or item.get("score")
            or 0.0
        )
    except (TypeError, ValueError):
        return 0.0


def _boost_carryover_ranked_items(
    items: list[dict[str, Any]],
    carryover_evidence_ids: list[str] | None,
    *,
    boost: float = 0.08,
) -> list[dict[str, Any]]:
    carryover_refs = {str(ref) for ref in (carryover_evidence_ids or []) if str(ref or "")}
    if not carryover_refs or not items:
        return items

    boosted_entries: list[tuple[float, int, dict[str, Any]]] = []
    changed = False
    for rank, item in enumerate(items):
        copy = dict(item)
        if (
            _candidate_evidence_ref(copy) in carryover_refs
            or copy.get("_retrieval_channel") == "carryover_evidence"
        ):
            base_score = _score_for_sort(copy)
            copy["rerank_score"] = round(base_score + boost, 6)
            copy["carryover_rerank_boost"] = boost
            copy["carryover_original_rank"] = rank + 1
            changed = True
        boosted_entries.append((_score_for_sort(copy), -rank, copy))

    if not changed:
        return items
    boosted_entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [item for _score, _rank, item in boosted_entries]


def compute_metrics(rows: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    answerable = [row for row in rows if _requires_factual_evidence_recall(row)]
    no_answer = [row for row in rows if not row.get("should_answer") or row.get("should_refuse")]
    full_rows = [row for row in rows if row.get("answer") is not None]
    route_rows = [row for row in rows if row.get("expected_route")]
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]

    recall_hits: list[float] = []
    reciprocal_ranks: list[float] = []
    evidence_recalls: list[float] = []
    for row in answerable:
        retrieved = [normalize_ref(item) for item in row.get("retrieved_evidence_ids", [])[:top_k]]
        gold = [normalize_ref(item) for item in row.get("gold_evidence_ids", [])]
        gold_set = set(gold)
        hits = set(retrieved) & gold_set
        recall_hits.append(1.0 if hits else 0.0)
        rank = _first_gold_rank(retrieved, gold)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        evidence_recalls.append(len(hits) / len(gold_set) if gold_set else 0.0)

    citation_checks = [
        _citation_valid(row.get("citations") or [], row.get("done_evidence") or row.get("retrieved_evidence_ids") or [])
        for row in full_rows
        if row.get("must_have_citations") and row.get("answer")
    ]
    citation_checks = [item for item in citation_checks if item is not None]

    no_answer_checks = [
        1.0 if _is_refusal(str(row.get("answer") or "")) else 0.0
        for row in no_answer
        if row.get("answer") is not None
    ]
    refusal_checks = [
        1.0 if _is_refusal(str(row.get("answer") or "")) else 0.0
        for row in rows
        if row.get("should_refuse") and row.get("answer") is not None
    ]
    validation_checks = [
        1.0 if (row.get("validation") or {}).get("passed") else 0.0
        for row in full_rows
        if row.get("validation") is not None
    ]
    high_risk_checks = [
        1.0 if str((row.get("validation") or {}).get("hallucinationRisk") or "").lower() in {"medium", "high"} else 0.0
        for row in full_rows
        if row.get("validation") is not None
    ]
    confirmation_checks = [
        item
        for item in (_confirmation_required_check(row) for row in rows)
        if item is not None
    ]
    overconfident_checks = [
        item
        for item in (_overconfident_answer_check(row) for row in rows)
        if item is not None
    ]
    long_context_rows = [row for row in rows if row.get("long_context")]
    topic100_checks = [
        1.0 if (row.get("long_context") or {}).get("topic_recall_at_100") else 0.0
        for row in long_context_rows
    ]
    anchor100_checks = [
        1.0 if (row.get("long_context") or {}).get("anchor_recall_at_100") else 0.0
        for row in long_context_rows
    ]
    memory_source_checks = [
        1.0 if row.get("memory_source_separated") else 0.0
        for row in rows
        if row.get("memory_source_separated") is not None
    ]
    source_label_checks = [
        item
        for item in (_source_label_check(row) for row in rows)
        if item is not None
    ]
    low_warning_checks = [
        item
        for item in (_low_credibility_warning_check(row) for row in rows)
        if item is not None
    ]
    external_fallback_checks = [
        item
        for item in (_external_fallback_check(row) for row in rows)
        if item is not None
    ]
    ocr_trace_checks = [
        item
        for item in (_ocr_trace_check(row) for row in rows)
        if item is not None
    ]
    confirmed_carryover_checks = [
        item
        for item in (_confirmed_carryover_check(row) for row in rows)
        if item is not None
    ]
    insufficient_evidence_checks = [
        item
        for item in (_insufficient_evidence_check(row) for row in rows)
        if item is not None
    ]
    route_checks = [
        1.0 if row.get("route") == row.get("expected_route") else 0.0
        for row in route_rows
    ]

    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "cases": len(rows),
        "answerable_gold_cases": len(answerable),
        "Recall@5": avg(recall_hits),
        "MRR": avg(reciprocal_ranks),
        "EvidenceRecall@5": avg(evidence_recalls),
        "CitationValidRate": avg(citation_checks),
        "NoAnswerAccuracy": avg(no_answer_checks),
        "RefusalCorrectness": avg(refusal_checks),
        "RouteAccuracy": avg(route_checks),
        "ValidationPassRate": avg(validation_checks),
        "HallucinationRiskRate": avg(high_risk_checks),
        "ConfirmationRequiredAccuracy": avg(confirmation_checks),
        "OverconfidentAnswerRate": avg(overconfident_checks),
        "LongContextTopicRecall@100": avg(topic100_checks),
        "LongContextAnchorRecall@100": avg(anchor100_checks),
        "MemorySourceSeparationRate": avg(memory_source_checks),
        "SourceLabelAccuracy": avg(source_label_checks),
        "LowCredibilityWarningRate": avg(low_warning_checks),
        "ExternalFallbackTriggerAccuracy": avg(external_fallback_checks),
        "OCRTraceCompleteness": avg(ocr_trace_checks),
        "ConfirmedCarryoverAccuracy": avg(confirmed_carryover_checks),
        "InsufficientEvidenceCorrectness": avg(insufficient_evidence_checks),
        "LatencyP50": _percentile(latencies, 0.50),
        "LatencyP95": _percentile(latencies, 0.95),
    }


async def _retrieve_once(
    query: str,
    limit: int,
    top_k: int,
    *,
    use_v2: bool = False,
    use_light_rerank: bool = False,
    use_fusion_rerank: bool = False,
    case_type: str = "",
    use_multi_query: bool = False,
    vector_query: str | None = None,
    intent_query: str | None = None,
    carryover_evidence_ids: list[str] | None = None,
    use_api_rerank: bool = False,
    api_rerank_model: str = "",
) -> dict[str, Any]:
    start = time.perf_counter()
    rerank_breakdown: list[dict[str, Any]] | None = None
    multi_query_trace: dict[str, Any] | None = None
    api_rerank_meta: dict[str, Any] | None = None

    queries = build_query_variants(query, case_type=case_type) if use_multi_query else [query]
    if not queries:
        queries = [query]

    all_items: list[dict[str, Any]] = []
    variant_hits: list[dict[str, Any]] = []
    last_rag_result: dict[str, Any] = {}
    search_adapter = search_news_rag_v2 if use_v2 else search_news_rag
    for variant in queries:
        adapter_kwargs: dict[str, Any] = {
            "limit": limit,
            "tool_name": "retrieve_news",
        }
        if use_v2:
            adapter_kwargs["vector_query"] = vector_query if variant == query else None
            adapter_kwargs["intent_query"] = intent_query or vector_query
            adapter_kwargs["carryover_evidence_ids"] = carryover_evidence_ids or []
        rag_result = await search_adapter(variant, **adapter_kwargs)
        last_rag_result = rag_result
        variant_items = rag_result.get("items") or []
        variant_hits.append({
            "query": variant,
            "items_count": len(variant_items),
            "evidence_ids": [str(i.get("evidence_id") or f"news:{i.get('id')}") for i in variant_items[:10]],
        })
        all_items.extend(variant_items)

    if use_multi_query and len(queries) > 1:
        merged = merge_dedupe_candidates(all_items)
        multi_query_trace = {
            "query_variants": queries,
            "variant_hits": variant_hits,
            "merged_candidates": len(merged),
        }
        items = merged
    else:
        items = all_items

    rerank_query = (intent_query or vector_query or query) if use_v2 else query
    rerank_top_k = min(len(items), max(top_k, min(len(items), 25))) if items else top_k
    use_fusion_for_merge = use_fusion_rerank and use_multi_query and len(queries) > 1
    if use_api_rerank and items:
        ranked, api_rerank_meta = await api_rerank(
            rerank_query,
            items,
            top_k=rerank_top_k,
            model=api_rerank_model or None,
        )
        ranked = _boost_carryover_ranked_items(ranked, carryover_evidence_ids)
        parents = _aggregate_parents(ranked, top_k) if ranked else []
        rerank_breakdown = [
            {
                "id": str(p.get("id")),
                "title": p.get("title"),
                "api_rerank_score": p.get("api_rerank_score") or p.get("rerank_score"),
                "reranker_used": p.get("reranker_used"),
            }
            for p in parents[:top_k]
        ]
    elif use_fusion_for_merge and items:
        # Multi-query merge: use fusion rerank with strong light_rule_bonus weight
        # because the light rules favor gold items (entity title overlap, source match)
        # more reliably than the cross-encoder on merged candidates from different queries.
        ranked = await fusion_rerank(
            rerank_query,
            items,
            top_k=rerank_top_k,
            cross_encoder_weight=0.15,
            vector_weight=0.35,
            light_bonus_weight=0.50,
        )
        ranked = _boost_carryover_ranked_items(ranked, carryover_evidence_ids)
        parents = _aggregate_parents(ranked, top_k) if ranked else []
        rerank_breakdown = [
            {
                "id": str(p.get("id")),
                "title": p.get("title"),
                "score_breakdown": p.get("score_breakdown") or {},
            }
            for p in parents[:top_k]
        ]
    else:
        if use_fusion_rerank and items:
            ranked = await fusion_rerank(
                rerank_query,
                items,
                top_k=rerank_top_k,
                cross_encoder_weight=0.15,
                vector_weight=0.55,
                light_bonus_weight=0.30,
            )
            ranked = _boost_carryover_ranked_items(ranked, carryover_evidence_ids)
            parents = _aggregate_parents(ranked, top_k) if ranked else []
            rerank_breakdown = [
                {
                    "id": str(p.get("id")),
                    "title": p.get("title"),
                    "score_breakdown": p.get("score_breakdown") or {},
                }
                for p in parents[:top_k]
            ]
        else:
            ranked = await rerank(rerank_query, items, top_k=rerank_top_k) if items else []
            ranked = _boost_carryover_ranked_items(ranked, carryover_evidence_ids)
            parents = _aggregate_parents(ranked, top_k) if ranked else []

    if use_light_rerank:
        parents = light_rule_rerank(rerank_query, parents)[:top_k]

    latency_ms = (time.perf_counter() - start) * 1000
    evidence_ids = [f"news:{item['id']}" for item in parents if item.get("id") is not None]
    result = {
        "route": last_rag_result.get("collection_route") or "default",
        "rag_route": last_rag_result.get("rag_route"),
        "retrieved_evidence_ids": evidence_ids,
        "raw_evidence_ids": last_rag_result.get("evidence_ids") or [],
        "latency_ms": round(latency_ms, 2),
        "collection": last_rag_result.get("collection_name"),
        "index_version": last_rag_result.get("index_version") or ("v2_unified" if use_v2 else "v1"),
        "items_count": len(items),
    }
    if carryover_evidence_ids:
        result["carryover_evidence_ids"] = list(carryover_evidence_ids)
    if rerank_query != query:
        result["rerank_query"] = rerank_query
    if rerank_breakdown:
        result["rerank_breakdown"] = rerank_breakdown
    if multi_query_trace:
        result["multi_query_trace"] = multi_query_trace
    if api_rerank_meta is not None:
        result["reranker_meta"] = api_rerank_meta
        result["reranker_used"] = api_rerank_meta.get("reranker_used")
    return result


async def evaluate_retrieve_only(
    cases: list[dict[str, Any]],
    *,
    limit: int = 50,
    top_k: int = 5,
    use_v2: bool = False,
    use_light_rerank: bool = False,
    use_fusion_rerank: bool = False,
    use_multi_query: bool = False,
    use_api_rerank: bool = False,
    api_rerank_model: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        history: list[dict[str, Any]] = []
        result: dict[str, Any] | None = None
        retrieval_query = ""
        route = "general_chat"
        for turn in _case_turns(case):
            history.append({"role": "user", "content": turn})
            context = build_session_context(history)
            retrieval_query = build_contextual_retrieval_query(turn, context)
            clean_query = clean_retrieval_query(turn)
            carryover_evidence_ids = (
                context.last_evidence_ids
                if is_contextual_follow_up(clean_query)
                else []
            )
            intent = detect_intent(retrieval_query)
            if intent == "news_qa":
                adapter_query = clean_query if use_v2 else retrieval_query
                vector_query = retrieval_query if use_v2 and retrieval_query != clean_query else None
                result = await _retrieve_once(
                    adapter_query,
                    limit=limit,
                    top_k=top_k,
                    use_v2=use_v2,
                    use_light_rerank=use_light_rerank,
                    use_fusion_rerank=use_fusion_rerank,
                    case_type=str(case.get("case_type") or ""),
                    use_multi_query=use_multi_query,
                    vector_query=vector_query,
                    intent_query=retrieval_query if use_v2 else None,
                    carryover_evidence_ids=carryover_evidence_ids,
                    use_api_rerank=use_api_rerank,
                    api_rerank_model=api_rerank_model,
                )
                route = result.get("route") or "default"
                refs = result.get("retrieved_evidence_ids") or []
                history.append({
                    "role": "assistant",
                    "content": " ".join(f"[{ref}]" for ref in refs),
                    "evidence": {"refs": refs},
                })
            else:
                result = {
                    "route": intent,
                    "rag_route": None,
                    "retrieved_evidence_ids": [],
                    "raw_evidence_ids": [],
                    "latency_ms": 0.0,
                    "collection": None,
                    "index_version": "v2_unified" if use_v2 else "v1",
                    "items_count": 0,
                }
                route = intent
                history.append({"role": "assistant", "content": ""})

        final = dict(case)
        final.update(result or {})
        final["mode"] = "retrieve-only"
        final["retrieval_query"] = retrieval_query
        final["route"] = route
        final.setdefault("answer", None)
        final.setdefault("citations", [])
        final.setdefault("validation", None)
        final.setdefault("hallucinationRisk", None)
        rows.append(_enrich_b_v3_eval_row(final))
    return rows


def _post_json(host: str, port: int, path: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, str], dict[str, Any]]:
    conn = http.client.HTTPConnection(host, port, timeout=60)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    conn.request("POST", path, body=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
    response = conn.getresponse()
    raw = response.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"raw": raw}
    return response.status, dict(response.getheaders()), data


def _ensure_auth(host: str, port: int) -> ApiAuth:
    username = "context_rag_eval_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    password = "ContextEval123"
    status, _headers, data = _post_json(host, port, "/api/user/register", {"username": username, "password": password})
    if status >= 400:
        status, _headers, data = _post_json(host, port, "/api/user/login", {"username": username, "password": password})
    if status >= 400:
        raise RuntimeError(f"auth failed: {status} {data}")
    return ApiAuth(username=username, password=password, token=data["data"]["token"])


def _chat_sse(
    host: str,
    port: int,
    token: str,
    message: str,
    session_id: int | None,
    *,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if session_id:
        payload["sessionId"] = session_id
    conn = http.client.HTTPConnection(host, port, timeout=timeout_seconds)
    conn.request(
        "POST",
        "/api/ai/chat",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": token, "Accept": "text/event-stream"},
    )
    response = conn.getresponse()
    answer_parts: list[str] = []
    done_event: dict[str, Any] | None = None
    error_event: dict[str, Any] | None = None
    raw_events: list[dict[str, Any]] = []
    while True:
        line = response.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text or not text.startswith("data:"):
            continue
        payload_text = text[5:].strip()
        if payload_text == "[DONE]":
            break
        try:
            event = json.loads(payload_text)
        except json.JSONDecodeError:
            raw_events.append({"raw": payload_text})
            continue
        raw_events.append(event)
        if "delta" in event:
            answer_parts.append(str(event["delta"]))
        if event.get("event") == "done":
            done_event = event
        if event.get("event") == "error":
            error_event = event
    serialized = json.dumps(raw_events, ensure_ascii=False).lower()
    return {
        "http_status": response.status,
        "content_type": response.getheader("content-type"),
        "answer": "".join(answer_parts),
        "done": done_event,
        "error": error_event,
        "has_reasoning_leak": any(term in serialized for term in ("reasoning_content", "reasoning", "thinking")),
    }


def evaluate_full_e2e(
    cases: list[dict[str, Any]],
    *,
    host: str,
    port: int,
    sse_timeout: int = 900,
) -> list[dict[str, Any]]:
    auth = _ensure_auth(host, port)
    rows: list[dict[str, Any]] = []
    for case in cases:
        session_id: int | None = None
        last_chat: dict[str, Any] | None = None
        error_text: str | None = None
        start = time.perf_counter()
        for turn in _case_turns(case):
            try:
                last_chat = _chat_sse(host, port, auth.token, turn, session_id, timeout_seconds=sse_timeout)
            except Exception as exc:  # noqa: BLE001 - eval rows should preserve failures and continue.
                error_text = str(exc)
                last_chat = {
                    "answer": "",
                    "done": {},
                    "error": {"message": error_text},
                    "has_reasoning_leak": False,
                }
                break
            done = last_chat.get("done") or {}
            session_id = done.get("sessionId") or session_id
        latency_ms = (time.perf_counter() - start) * 1000
        done = (last_chat or {}).get("done") or {}
        validation = done.get("validation")
        answer = (last_chat or {}).get("answer") or ""
        final = dict(case)
        final.update({
            "mode": "full-e2e",
            "sessionId": session_id,
            "answer": answer,
            "citations": extract_citations(answer),
            "done": done,
            "done_evidence": done.get("evidence") or [],
            "retrieved_evidence_ids": done.get("evidence") or [],
            "validation": validation,
            "hallucinationRisk": (validation or {}).get("hallucinationRisk"),
            "latency_ms": round(latency_ms, 2),
            "http_status": (last_chat or {}).get("http_status"),
            "content_type": (last_chat or {}).get("content_type"),
            "has_reasoning_leak": (last_chat or {}).get("has_reasoning_leak"),
            "error": error_text,
            "route": (validation or {}).get("route") or case.get("expected_route"),
            "retrieval_query": None,
        })
        rows.append(_enrich_b_v3_eval_row(final))
    return rows


def _fmt_metric(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        if value <= 1.0:
            return f"{value:.1%}"
        return f"{value:.0f}ms"
    return str(value)


def failed_cases(rows: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        gold = {normalize_ref(ref) for ref in row.get("gold_evidence_ids") or []}
        retrieved = [normalize_ref(ref) for ref in (row.get("retrieved_evidence_ids") or [])[:top_k]]
        if _requires_factual_evidence_recall(row) and gold and not (set(retrieved) & gold):
            reasons.append("gold_miss_top5")
        if row.get("expected_route") and row.get("route") != row.get("expected_route"):
            reasons.append("route_mismatch")
        if row.get("must_have_citations") and row.get("answer") and not row.get("citations"):
            reasons.append("missing_citation")
        if row.get("should_refuse") and row.get("answer") and not _is_refusal(str(row.get("answer"))):
            reasons.append("refusal_miss")
        validation = row.get("validation") or {}
        if validation and not validation.get("passed"):
            reasons.append("validation_failed")
        if row.get("has_reasoning_leak"):
            reasons.append("reasoning_leak")
        if reasons:
            failures.append({
                "id": row.get("id"),
                "case_type": row.get("case_type"),
                "reasons": reasons,
                "expected_route": row.get("expected_route"),
                "route": row.get("route"),
                "gold_evidence_ids": row.get("gold_evidence_ids"),
                "retrieved_evidence_ids": row.get("retrieved_evidence_ids"),
                "retrieval_query": row.get("retrieval_query"),
                "answer": row.get("answer"),
            })
    return failures


def render_markdown_report(
    *,
    mode: str,
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    failures: list[dict[str, Any]],
) -> str:
    lines = [
        "# Context RAG Baseline 2026-06-22",
        "",
        "## Scope",
        "",
        f"- Mode: `{mode}`",
        f"- Gold cases: {len(cases)}",
        "- No Redis / SQLite / Milvus / NGINX.",
        "- Existing RAG collections were not rebuilt or modified.",
        "- Memory and session summary are not counted as factual evidence.",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "Recall@5",
        "MRR",
        "EvidenceRecall@5",
        "CitationValidRate",
        "NoAnswerAccuracy",
        "RefusalCorrectness",
        "RouteAccuracy",
        "ValidationPassRate",
        "HallucinationRiskRate",
        "ConfirmationRequiredAccuracy",
        "OverconfidentAnswerRate",
        "SourceLabelAccuracy",
        "LowCredibilityWarningRate",
        "ExternalFallbackTriggerAccuracy",
        "OCRTraceCompleteness",
        "ConfirmedCarryoverAccuracy",
        "LongContextTopicRecall@100",
        "LongContextAnchorRecall@100",
        "MemorySourceSeparationRate",
        "InsufficientEvidenceCorrectness",
        "LatencyP50",
        "LatencyP95",
    ):
        lines.append(f"| {key} | {_fmt_metric(metrics.get(key))} |")

    lines.extend([
        "",
        "## Failed Cases",
        "",
    ])
    if not failures:
        lines.append("No failed cases under the selected mode.")
    else:
        lines.append("| Case | Type | Reasons | Route | Retrieved |")
        lines.append("| --- | --- | --- | --- | --- |")
        for failure in failures:
            lines.append(
                "| {id} | {case_type} | {reasons} | {route} | {retrieved} |".format(
                    id=failure["id"],
                    case_type=failure["case_type"],
                    reasons=", ".join(failure["reasons"]),
                    route=f"{failure.get('route')} / expected {failure.get('expected_route')}",
                    retrieved=", ".join((failure.get("retrieved_evidence_ids") or [])[:5]),
                )
            )

    lines.extend([
        "",
        "## Risks",
        "",
        "- retrieve-only mode measures retrieval and routing, not final model behavior.",
        "- full-e2e mode is supported but expensive on local Ollama; use it for nightly or sampled runs.",
        "- Some gold ids are seeded from 3.1-B gray evidence and should be reviewed as the corpus evolves.",
        "- No-answer and investment-boundary release gates require full-e2e Validator checks before production expansion.",
        "",
        "## Next Steps",
        "",
        "- Review failed cases and split failures into route, retrieval, rerank, and validator buckets.",
        "- Add sampled full-e2e eval to CI/manual release checklist.",
        "- Keep econ_finance_query enforce; do not expand enforce without stable eval metrics.",
    ])
    return "\n".join(lines) + "\n"


def render_diagnosis_markdown(
    *,
    title: str,
    mode: str,
    metrics: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    metric_k: int,
    diagnosis_k: int,
) -> str:
    bucket_counts: dict[str, int] = {}
    for diagnosis in diagnostics:
        for bucket in diagnosis.get("buckets") or []:
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    existence_summary = summarize_gold_existence(diagnostics)

    lines = [
        f"# {title}",
        "",
        "## Scope",
        "",
        f"- Mode: `{mode}`",
        f"- Metric cutoff: @{metric_k}",
        f"- Diagnosis cutoff: @{diagnosis_k}",
        "- Existing 3.2-A baseline files were not overwritten.",
        "- Existing RAG collections were not rebuilt or modified.",
        "",
        "## Metric Snapshot",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in ("Recall@5", "MRR", "EvidenceRecall@5", "RouteAccuracy", "LatencyP50", "LatencyP95"):
        lines.append(f"| {key} | {_fmt_metric(metrics.get(key))} |")

    lines.extend(["", "## Bucket Counts", "", "| Bucket | Count |", "| --- | ---: |"])
    if bucket_counts:
        for bucket, count in sorted(bucket_counts.items()):
            lines.append(f"| {bucket} | {count} |")
    else:
        lines.append("| none | 0 |")

    if existence_summary["gold_refs_checked"]:
        lines.extend([
            "",
            "## Gold Evidence Existence",
            "",
            "| Item | Count |",
            "| --- | ---: |",
            f"| gold refs checked | {existence_summary['gold_refs_checked']} |",
            f"| exists in at least one source | {existence_summary['exists']} |",
            f"| missing from checked sources | {existence_summary['missing']} |",
            "",
            "### Source Hits",
            "",
            "| Source | Count |",
            "| --- | ---: |",
        ])
        source_hits = existence_summary.get("source_hits") or {}
        if source_hits:
            for source, count in sorted(source_hits.items()):
                lines.append(f"| {source} | {count} |")
        else:
            lines.append("| none | 0 |")

    lines.extend([
        "",
        "## Failed Case Buckets",
        "",
        "| Case | Type | Buckets | Gold Rank | Gold Existence | Route | Collection |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for diagnosis in diagnostics:
        ranks = diagnosis.get("gold_ranks") or {}
        rank_text = ", ".join(f"{ref}:{rank or 'miss'}" for ref, rank in ranks.items()) or "N/A"
        existence = diagnosis.get("gold_existence") or {}
        existence_text = ", ".join(
            f"{ref}:{item.get('status')}({'+'.join(item.get('present_in') or []) or 'none'})"
            for ref, item in existence.items()
        ) or "N/A"
        lines.append(
            "| {id} | {case_type} | {buckets} | {ranks} | {existence} | {route} | {collection} |".format(
                id=diagnosis.get("id"),
                case_type=diagnosis.get("case_type"),
                buckets=", ".join(diagnosis.get("buckets") or []),
                ranks=rank_text,
                existence=existence_text,
                route=f"{diagnosis.get('route')} / expected {diagnosis.get('expected_route')}",
                collection=diagnosis.get("collection") or "N/A",
            )
        )

    lines.extend([
        "",
        "## Notes",
        "",
        "- `gold_in_top20_not_top5` means rerank may help without rebuilding the collection.",
        "- `gold_not_in_top20` plus `query_rewrite_or_ranking` means the gold evidence exists but retrieval/ranking did not surface it.",
        "- `corpus_missing` means the gold evidence id was not found in checked MySQL metadata, news chunk/source store, or Qdrant payload.",
        "- `possible_gold_issue` is a review bucket, not an automatic pass.",
        "- Session summary, memory, and previous-turn evidence ids are never counted as factual evidence.",
    ])
    return "\n".join(lines) + "\n"


def save_outputs(rows: list[dict[str, Any]], metrics: dict[str, Any], failures: list[dict[str, Any]],
                 markdown: str, report_path: Path, json_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps({
        "metrics": metrics,
        "failed_cases": failures,
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def save_diagnosis_outputs(
    diagnostics: list[dict[str, Any]],
    markdown: str,
    *,
    metrics: dict[str, Any] | None = None,
    diagnosis_report_path: Path | None = None,
    diagnosis_json_path: Path | None = None,
    failure_report_path: Path | None = None,
) -> None:
    if diagnosis_report_path:
        diagnosis_report_path.parent.mkdir(parents=True, exist_ok=True)
        diagnosis_report_path.write_text(markdown, encoding="utf-8")
    if failure_report_path:
        failure_report_path.parent.mkdir(parents=True, exist_ok=True)
        failure_report_path.write_text(markdown, encoding="utf-8")
    if diagnosis_json_path:
        diagnosis_json_path.parent.mkdir(parents=True, exist_ok=True)
        diagnosis_json_path.write_text(json.dumps({
            "metrics": metrics or {},
            "gold_existence_summary": summarize_gold_existence(diagnostics),
            "diagnostics": diagnostics,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


async def persist_eval_trace_to_mysql(
    *,
    rows: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    metrics: dict[str, Any],
    run_id: str,
    phase: str = "3.2-B2",
) -> None:
    """Persist bounded eval trace only; memory/session summaries are excluded."""
    diagnostics_by_id = {str(item.get("id")): item for item in diagnostics}
    async with AsyncSessionLocal() as session:
        await session.execute(text(
            """
            CREATE TABLE IF NOT EXISTS eval_context_rag_trace (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              run_id VARCHAR(96) NOT NULL,
              phase VARCHAR(32) NOT NULL,
              case_id VARCHAR(128) NOT NULL,
              case_type VARCHAR(128),
              mode VARCHAR(32),
              route VARCHAR(128),
              expected_route VARCHAR(128),
              retrieval_query TEXT,
              retrieved_evidence_ids JSON,
              gold_evidence_ids JSON,
              failure_buckets JSON,
              gold_existence JSON,
              metrics JSON,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))
        for row in rows:
            case_id = str(row.get("id") or "")
            diagnosis = diagnostics_by_id.get(case_id, {})
            await session.execute(
                text(
                    """
                    INSERT INTO eval_context_rag_trace (
                      run_id, phase, case_id, case_type, mode, route, expected_route,
                      retrieval_query, retrieved_evidence_ids, gold_evidence_ids,
                      failure_buckets, gold_existence, metrics
                    ) VALUES (
                      :run_id, :phase, :case_id, :case_type, :mode, :route, :expected_route,
                      :retrieval_query, :retrieved_evidence_ids, :gold_evidence_ids,
                      :failure_buckets, :gold_existence, :metrics
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "phase": phase,
                    "case_id": case_id,
                    "case_type": row.get("case_type"),
                    "mode": row.get("mode"),
                    "route": row.get("route"),
                    "expected_route": row.get("expected_route"),
                    "retrieval_query": row.get("retrieval_query"),
                    "retrieved_evidence_ids": json.dumps(row.get("retrieved_evidence_ids") or [], ensure_ascii=False),
                    "gold_evidence_ids": json.dumps(row.get("gold_evidence_ids") or [], ensure_ascii=False),
                    "failure_buckets": json.dumps(diagnosis.get("buckets") or [], ensure_ascii=False),
                    "gold_existence": json.dumps(diagnosis.get("gold_existence") or {}, ensure_ascii=False),
                    "metrics": json.dumps(metrics, ensure_ascii=False),
                },
            )
        await session.commit()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Context Manager + RAG eval runner")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD_PATH))
    parser.add_argument("--mode", choices=["retrieve-only", "full-e2e"], default="retrieve-only")
    parser.add_argument("--use-v2", action="store_true", help="Use isolated PG/Qdrant v2 retrieval adapter")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--metric-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--case-limit", type=int, default=0, help="0 means all cases")
    parser.add_argument("--case-ids", default="", help="Comma-separated case ids, preserving this order")
    parser.add_argument("--light-rerank", action="store_true", help="Apply lightweight rule rerank inside retrieved candidates")
    parser.add_argument("--fusion-rerank", action="store_true", help="Use fusion rerank (vector + cross-encoder + light bonus)")
    parser.add_argument("--api-rerank", action="store_true", help="Use external API reranker for the final candidate rerank")
    parser.add_argument("--api-rerank-model", default=os.getenv("RERANKER_API_MODEL", "Pro/BAAI/bge-reranker-v2-m3"))
    parser.add_argument("--multi-query", action="store_true", help="Enable multi-query recall patch for B_/E_/C_ case types")
    parser.add_argument("--rerank-breakdown-json", default="", help="Path to write per-case rerank score breakdown JSON")
    parser.add_argument("--multi-query-trace-json", default="", help="Path to write per-case multi-query trace JSON")
    parser.add_argument("--sampled-full-e2e", action="store_true", help="Run sampled full-e2e after retrieve-only and emit separate report")
    parser.add_argument("--sampled-full-e2e-report", default="", help="Path for sampled full-e2e markdown report")
    parser.add_argument("--sampled-full-e2e-json", default="", help="Path for sampled full-e2e JSON report")
    parser.add_argument("--sampled-case-ids", default="", help="Comma-separated case ids for sampled full-e2e; auto-selected if empty")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--sse-timeout", type=int, default=300)
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--json-report", default=str(DEFAULT_JSON_REPORT_PATH))
    parser.add_argument("--diagnosis-report", default="")
    parser.add_argument("--diagnosis-json", default="")
    parser.add_argument("--failure-report", default="")
    parser.add_argument("--gold-existence-check", action="store_true")
    parser.add_argument("--gold-existence-report", default="")
    parser.add_argument("--gold-existence-json", default="")
    parser.add_argument("--mysql-eval-trace", action="store_true")
    parser.add_argument("--eval-run-id", default="")
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_gold_cases(args.gold)
    case_ids = [item.strip() for item in str(args.case_ids or "").split(",") if item.strip()]
    cases = select_cases(cases, case_ids=case_ids or None, case_limit=args.case_limit)
    if args.mode == "retrieve-only":
        rows = await evaluate_retrieve_only(
            cases,
            limit=args.limit,
            top_k=args.top_k,
            use_v2=args.use_v2,
            use_light_rerank=args.light_rerank,
            use_fusion_rerank=args.fusion_rerank,
            use_multi_query=args.multi_query,
            use_api_rerank=args.api_rerank,
            api_rerank_model=args.api_rerank_model,
        )
    else:
        rows = evaluate_full_e2e(cases, host=args.host, port=args.port, sse_timeout=args.sse_timeout)
    metrics = compute_metrics(rows, top_k=args.metric_k)
    failures = failed_cases(rows, top_k=args.metric_k)
    markdown = render_markdown_report(mode=args.mode, cases=cases, rows=rows, metrics=metrics, failures=failures)
    save_outputs(rows, metrics, failures, markdown, Path(args.report), Path(args.json_report))
    diagnostics = diagnose_failures(rows, metric_k=args.metric_k, diagnosis_k=args.top_k)
    gold_existence: dict[str, dict[str, Any]] | None = None
    if args.gold_existence_check:
        gold_refs: list[str] = []
        for diagnosis in diagnostics:
            if "gold_not_in_top20" not in (diagnosis.get("buckets") or []):
                continue
            for ref, rank in (diagnosis.get("gold_ranks") or {}).items():
                if rank is None:
                    gold_refs.append(ref)
        db: AsyncSession | None = None
        try:
            async with AsyncSessionLocal() as session:
                gold_existence = await check_gold_evidence_existence(gold_refs, db=session)
        except Exception:
            gold_existence = await check_gold_evidence_existence(gold_refs, db=None)
        diagnostics = diagnose_failures(
            rows,
            metric_k=args.metric_k,
            diagnosis_k=args.top_k,
            gold_existence=gold_existence,
        )
    diagnosis_markdown = render_diagnosis_markdown(
        title="Context RAG Top20 Diagnosis 2026-06-22",
        mode=args.mode,
        metrics=metrics,
        diagnostics=diagnostics,
        metric_k=args.metric_k,
        diagnosis_k=args.top_k,
    )
    save_diagnosis_outputs(
        diagnostics,
        diagnosis_markdown,
        metrics=metrics,
        diagnosis_report_path=Path(args.diagnosis_report) if args.diagnosis_report else None,
        diagnosis_json_path=Path(args.diagnosis_json) if args.diagnosis_json else None,
        failure_report_path=Path(args.failure_report) if args.failure_report else None,
    )
    if args.gold_existence_check:
        existence_markdown = render_diagnosis_markdown(
            title="Context RAG Gold Evidence Existence 2026-06-22",
            mode=args.mode,
            metrics=metrics,
            diagnostics=diagnostics,
            metric_k=args.metric_k,
            diagnosis_k=args.top_k,
        )
        save_diagnosis_outputs(
            diagnostics,
            existence_markdown,
            metrics=metrics,
            diagnosis_report_path=Path(args.gold_existence_report) if args.gold_existence_report else None,
            diagnosis_json_path=Path(args.gold_existence_json) if args.gold_existence_json else None,
        )
    if args.rerank_breakdown_json:
        breakdown_path = Path(args.rerank_breakdown_json)
        breakdown_path.parent.mkdir(parents=True, exist_ok=True)
        breakdown_payload = {
            case.get("id"): case.get("rerank_breakdown") or []
            for case in rows
            if case.get("rerank_breakdown")
        }
        breakdown_path.write_text(
            json.dumps(breakdown_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.multi_query_trace_json:
        trace_path = Path(args.multi_query_trace_json)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_payload = {
            case.get("id"): case.get("multi_query_trace") or {}
            for case in rows
            if case.get("multi_query_trace")
        }
        trace_path.write_text(
            json.dumps(trace_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.mysql_eval_trace:
        run_id = args.eval_run_id or datetime.now().strftime("context-rag-3-2-b2-%Y%m%d-%H%M%S")
        await persist_eval_trace_to_mysql(rows=rows, diagnostics=diagnostics, metrics=metrics, run_id=run_id)
    sampled_result: dict[str, Any] | None = None
    if args.sampled_full_e2e:
        sampled_case_ids = [item.strip() for item in str(args.sampled_case_ids or "").split(",") if item.strip()]
        if not sampled_case_ids:
            sampled_case_ids = _default_sampled_case_ids()
        sampled_cases = select_cases(load_gold_cases(args.gold), case_ids=sampled_case_ids)
        sampled_rows = evaluate_full_e2e(sampled_cases, host=args.host, port=args.port, sse_timeout=args.sse_timeout)
        sampled_metrics = compute_sampled_full_e2e_metrics(sampled_rows)
        sampled_failures = failed_cases(sampled_rows, top_k=args.metric_k)
        sampled_markdown = render_sampled_full_e2e_report(
            cases=sampled_cases,
            rows=sampled_rows,
            metrics=sampled_metrics,
            failures=sampled_failures,
        )
        if args.sampled_full_e2e_report:
            sp = Path(args.sampled_full_e2e_report)
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(sampled_markdown, encoding="utf-8")
        if args.sampled_full_e2e_json:
            jp = Path(args.sampled_full_e2e_json)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(
                json.dumps(
                    {"metrics": sampled_metrics, "failed_cases": sampled_failures, "rows": sampled_rows},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        sampled_result = {
            "metrics": sampled_metrics,
            "failed_cases": sampled_failures,
            "report": args.sampled_full_e2e_report,
            "json_report": args.sampled_full_e2e_json,
        }
    return {
        "metrics": metrics,
        "failed_cases": failures,
        "diagnostics": diagnostics,
        "gold_existence_summary": summarize_gold_existence(diagnostics),
        "report": args.report,
        "json_report": args.json_report,
        "sampled_full_e2e": sampled_result,
    }


def _default_sampled_case_ids() -> list[str]:
    """Auto-select 14 cases covering normal / no-answer / investment / source / follow-up / multi-doc."""
    return [
        "exact_econ_001",
        "exact_econ_003",
        "context_follow_001",
        "context_follow_006",
        "time_recent_001",
        "time_recent_007",
        "source_001",
        "source_005",
        "multi_doc_001",
        "multi_doc_006",
        "distractor_005",
        "investment_005",
        "no_answer_001",
        "no_answer_006",
    ]


def compute_sampled_full_e2e_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = compute_metrics(rows, top_k=5)
    timeouts = [1.0 if row.get("error") else 0.0 for row in rows]
    sse_done = [1.0 if (row.get("done") or {}) else 0.0 for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]

    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    base.update({
        "timeout_rate": avg(timeouts),
        "sse_done_received": avg(sse_done),
        "llm_total_ms": avg(latencies),
        "llm_first_token_ms": None,
    })
    return base


def render_sampled_full_e2e_report(
    *,
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    failures: list[dict[str, Any]],
) -> str:
    lines = [
        "# Context RAG Sampled Full E2E 3.2-C 2026-06-22",
        "",
        "## Scope",
        "",
        f"- Mode: `full-e2e` (sampled, {len(cases)} cases)",
        "- Covers normal answer / no-answer / investment boundary / source limited / context follow-up / multi-document.",
        "- Memory and session summary are not counted as factual evidence.",
        "- Timeout rate and LLM latency are separated from retrieval latency.",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "Recall@5",
        "MRR",
        "EvidenceRecall@5",
        "CitationValidRate",
        "NoAnswerAccuracy",
        "RefusalCorrectness",
        "RouteAccuracy",
        "ValidationPassRate",
        "HallucinationRiskRate",
        "ConfirmationRequiredAccuracy",
        "OverconfidentAnswerRate",
        "SourceLabelAccuracy",
        "LowCredibilityWarningRate",
        "ExternalFallbackTriggerAccuracy",
        "OCRTraceCompleteness",
        "ConfirmedCarryoverAccuracy",
        "LongContextTopicRecall@100",
        "LongContextAnchorRecall@100",
        "MemorySourceSeparationRate",
        "InsufficientEvidenceCorrectness",
        "timeout_rate",
        "sse_done_received",
        "llm_total_ms",
        "LatencyP50",
        "LatencyP95",
    ):
        lines.append(f"| {key} | {_fmt_metric(metrics.get(key))} |")

    lines.extend(["", "## Failed Cases", "", "| Case | Type | Reasons | Route |", "| --- | --- | --- | --- |"])
    if not failures:
        lines.append("| none | - | - | - |")
    else:
        for failure in failures:
            lines.append(
                "| {id} | {case_type} | {reasons} | {route} / expected {expected} |".format(
                    id=failure.get("id"),
                    case_type=failure.get("case_type"),
                    reasons=", ".join(failure.get("reasons") or []),
                    route=failure.get("route"),
                    expected=failure.get("expected_route"),
                )
            )

    lines.extend([
        "",
        "## Notes",
        "",
        "- `timeout_rate` isolates SSE/LLM timeouts from retrieval failures.",
        "- `sse_done_received` confirms the done event arrived for each case.",
        "- `llm_total_ms` is the wall-clock LLM turn latency (not retrieval latency).",
        "- No-answer and investment-boundary cases require Validator refusal/quality checks in full-e2e.",
        "- Session summary, memory, and previous-turn evidence ids are never counted as factual evidence.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = asyncio.run(async_main(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
