"""Reusable helpers for building economy/policy retrieval chunks.

The original rebuild pipeline used helpers from a local ``work/`` experiment
folder.  These helpers are source code, so they live here instead of depending
on a runtime scratch directory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "policy_macro_manual_samples" / "samples.example.jsonl"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def stable_point_id(key: str) -> int:
    """Return a deterministic positive Qdrant integer id for a logical chunk."""

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def iter_docs(dataset: Path, max_docs: int | None = None) -> Iterable[dict[str, Any]]:
    count = 0
    with Path(dataset).open("r", encoding="utf-8") as handle:
        for line in handle:
            if max_docs is not None and count >= max_docs:
                break
            raw = line.strip()
            if not raw:
                continue
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                continue
            count += 1
            yield doc


def base_payload(doc: dict[str, Any]) -> dict[str, Any]:
    source = _text(doc.get("source") or doc.get("source_id") or doc.get("publisher"))
    source_doc_id = _text(doc.get("source_doc_id") or doc.get("document_id") or doc.get("old_news_id"))
    doc_id = _text(doc.get("doc_id") or (f"{source}:{source_doc_id}" if source and source_doc_id else source_doc_id))
    evidence_id = _text(doc.get("evidence_id") or (f"news:{doc_id}" if doc_id else ""))
    title = _text(doc.get("title"))
    summary = _text(doc.get("summary") or doc.get("abstract") or doc.get("description"))
    content = _text(doc.get("content") or doc.get("content_excerpt") or doc.get("text") or summary)
    url = _text(doc.get("url") or doc.get("source_url"))

    return {
        "id": doc_id,
        "news_id": doc_id,
        "doc_id": doc_id,
        "evidence_id": evidence_id,
        "source": source,
        "source_doc_id": source_doc_id,
        "title": title,
        "summary": summary,
        "content": content,
        "text": summary or content,
        "publish_time": doc.get("publish_time"),
        "publish_ts": _int(doc.get("publish_ts")),
        "section": _text(doc.get("section") or doc.get("document_type")),
        "category": _text(doc.get("category") or doc.get("policy_domain")),
        "url": url,
    }


def _body_chunks(text: str, *, size: int, overlap: int, limit: int) -> list[str]:
    text = _text(text)
    if not text:
        return []
    if size <= 0 or len(text) <= size:
        return [text]
    step = max(1, size - max(0, overlap))
    chunks: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        if limit > 0 and len(chunks) >= limit:
            break
        if start + size >= len(text):
            break
    return chunks


def _payload_for_chunk(base: dict[str, Any], *, chunk_type: str, chunk_index: int, chunk_text: str) -> dict[str, Any]:
    payload = dict(base)
    payload.update(
        {
            "chunk_type": chunk_type,
            "chunk_index": int(chunk_index),
            "chunk_text": chunk_text,
            "text": chunk_text,
        }
    )
    return payload


def make_points_for_doc(
    doc: dict[str, Any],
    *,
    collection: str,
    body_size: int,
    body_overlap: int,
    max_body_chunks: int,
) -> Iterable[tuple[str, dict[str, Any], str]]:
    base = base_payload(doc)
    evidence_id = base.get("evidence_id") or base.get("doc_id") or stable_point_id(json.dumps(doc, sort_keys=True))
    title = _text(base.get("title"))
    summary = _text(base.get("summary") or base.get("content"))
    summary_text = "\n".join(part for part in (title, summary) if part)
    if summary_text:
        payload = _payload_for_chunk(base, chunk_type="summary", chunk_index=0, chunk_text=summary_text)
        key = f"{collection}|{evidence_id}|summary|0"
        yield key, payload, summary_text

    for index, chunk in enumerate(
        _body_chunks(
            _text(base.get("content") or summary_text),
            size=body_size,
            overlap=body_overlap,
            limit=max_body_chunks,
        )
    ):
        payload = _payload_for_chunk(base, chunk_type="body", chunk_index=index, chunk_text=chunk)
        key = f"{collection}|{evidence_id}|body|{index}"
        embed_text = "\n".join(part for part in (title, chunk) if part)
        yield key, payload, embed_text
