"""API-backed reranker adapters for eval-only experiments.

The default production retrieval path does not import or use this module.
It is enabled explicitly from eval flags so experiments can verify whether an
external reranker was actually called.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable


DEFAULT_BASE_URL = os.getenv("RERANKER_API_BASE_URL", "https://api.siliconflow.cn/v1")
DEFAULT_MODEL = os.getenv("RERANKER_API_MODEL", "Pro/BAAI/bge-reranker-v2-m3")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("RERANKER_API_TIMEOUT_SECONDS", "90"))
DEFAULT_DOCUMENT_MAX_CHARS = int(os.getenv("RERANKER_API_DOCUMENT_MAX_CHARS", "1600"))
# Limits of the local ai-dev-stack hf-api /rerank endpoint (it returns 422 beyond them).
HF_API_MAX_DOCUMENTS = int(os.getenv("RERANKER_HF_API_MAX_DOCUMENTS", "32"))
HF_API_MAX_LENGTH = int(os.getenv("RERANKER_HF_API_MAX_LENGTH", "1024"))

RerankTransport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def _endpoint(base_url: str) -> str:
    cleaned = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if cleaned.endswith("/rerank"):
        return cleaned
    return f"{cleaned}/rerank"


def _document_text(item: dict[str, Any], *, max_chars: int = DEFAULT_DOCUMENT_MAX_CHARS) -> str:
    fields = [
        item.get("title"),
        item.get("summary"),
        item.get("snippet"),
        item.get("chunk_text"),
        item.get("text"),
    ]
    text = "\n".join(str(value).strip() for value in fields if str(value or "").strip())
    if not text:
        text = str(item.get("id") or item.get("evidence_id") or "")
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured API endpoint.
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"rerank api http {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"rerank api network error: {exc.reason}") from exc
    return json.loads(raw)


def _fallback(items: list[dict[str, Any]], top_k: int, reason: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return list(items[:top_k]), {
        "used": False,
        "reranker_used": "api_reranker_failed",
        "reason": reason,
        "api_calls": 0,
    }


def _rank_from_response(
    items: list[dict[str, Any]],
    response: dict[str, Any],
    *,
    top_k: int,
    model: str,
    elapsed_ms: float,
    reranker_used: str = "siliconflow_api",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[int] = set()
    ranked_entries: list[tuple[float, int, dict[str, Any]]] = []
    for rank_index, result in enumerate(response.get("results") or []):
        try:
            index = int(result.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items) or index in seen:
            continue
        seen.add(index)
        # SiliconFlow/Cohere style returns relevance_score; the local hf-api service returns score.
        score = float(result.get("relevance_score", result.get("score")) or 0.0)
        copy = dict(items[index])
        copy["rerank_score"] = round(score, 6)
        copy["api_rerank_score"] = round(score, 6)
        copy["reranker_used"] = reranker_used
        copy["reranker_model"] = model
        copy["reranker_rank"] = rank_index + 1
        ranked_entries.append((score, -rank_index, copy))

    ranked_entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    ranked = [item for _score, _rank, item in ranked_entries]
    for index, item in enumerate(items):
        if index in seen:
            continue
        copy = dict(item)
        copy.setdefault("reranker_used", f"{reranker_used}_unscored_tail")
        ranked.append(copy)

    meta = {
        "used": True,
        "reranker_used": reranker_used,
        "model": model,
        "api_calls": 1,
        "candidate_count": len(items),
        "ranked_count": len(ranked_entries),
        "latency_ms": round(elapsed_ms, 2),
        "tokens": (response.get("meta") or {}).get("tokens") or {},
        "billed_units": (response.get("meta") or {}).get("billed_units") or {},
    }
    return ranked[:top_k], meta


async def rerank_with_api(
    query: str,
    items: list[dict[str, Any]],
    top_k: int = 5,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    transport: RerankTransport | None = None,
    api_format: str = "siliconflow",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """api_format: "siliconflow" (Bearer key, Cohere-style payload) or "hf_api"
    (local hf-api service: no key, payload limited to model/query/documents)."""
    if not query or not items:
        return list(items[:top_k]), {
            "used": False,
            "reranker_used": "api_reranker_skipped",
            "reason": "empty_query_or_items",
            "api_calls": 0,
        }

    eff_top_k = max(1, min(int(top_k), len(items)))
    hf_api = api_format == "hf_api"
    eff_key = api_key or os.getenv("SILICONFLOW_API_KEY") or os.getenv("RERANKER_API_KEY")
    if not eff_key and not hf_api:
        return _fallback(items, eff_top_k, "missing_api_key")

    eff_model = model or DEFAULT_MODEL
    documents = [_document_text(item) for item in items]
    headers = {"Content-Type": "application/json"}
    if eff_key:
        headers["Authorization"] = f"Bearer {eff_key}"
    if hf_api:
        # hf-api rejects (HTTP 422) more than 32 documents per request and inputs over max_length
        # tokens unless truncate=true, and returns only top_n (default 5) scores. Cross-encoder
        # scores are per (query, doc) pair, so batches can be merged and ranked together.
        batch_size = max(1, HF_API_MAX_DOCUMENTS)
        payloads = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start:start + batch_size]
            payloads.append({"model": eff_model, "query": query, "documents": batch, "top_n": len(batch),
                             "truncate": True, "max_length": HF_API_MAX_LENGTH, "batch_size": 8})
    else:
        batch_size = len(documents)
        payloads = [{
            "model": eff_model,
            "query": query,
            "documents": documents,
            "return_documents": False,
            "top_n": len(items),
            "max_chunks_per_doc": 1024,
            "overlap_tokens": 80,
        }]
    call = transport or _post_json
    start = time.perf_counter()
    results: list[dict[str, Any]] = []
    try:
        for batch_index, payload in enumerate(payloads):
            response = await asyncio.to_thread(
                call,
                _endpoint(base_url or DEFAULT_BASE_URL),
                headers,
                payload,
                float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
            )
            offset = batch_index * batch_size
            for result in response.get("results") or []:
                try:
                    results.append({**result, "index": int(result.get("index")) + offset})
                except (TypeError, ValueError):
                    continue
    except Exception as exc:  # noqa: BLE001 - eval experiment must preserve fallback behavior.
        return _fallback(items, eff_top_k, str(exc))

    elapsed_ms = (time.perf_counter() - start) * 1000
    try:
        ranked, meta = _rank_from_response(
            items,
            {"results": results, "meta": response.get("meta") or {}},
            top_k=eff_top_k,
            model=eff_model,
            elapsed_ms=elapsed_ms,
            reranker_used="hf_api" if hf_api else "siliconflow_api",
        )
    except Exception as exc:  # noqa: BLE001 - malformed provider response should not abort eval.
        return _fallback(items, eff_top_k, f"invalid_api_response: {exc}")
    meta["api_calls"] = len(payloads)
    return ranked, meta


__all__ = ["rerank_with_api"]
