"""Deterministic lexical and hybrid ranking helpers for RAG candidates."""

from __future__ import annotations

from datetime import datetime
import re
import time
from typing import Any

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_TERM_RE = re.compile(r"[a-zA-Z0-9]+")
DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")

ARTIFACT_PATTERNS = (
    "nannann",
    "｜nan",
    "|nan",
    "nan政协",
    "nan国家",
)

CLICKBAIT_PATTERNS = (
    "吵翻",
    "掀桌",
    "傻乎乎",
    "捞女",
    "无人问津",
    "躲不开",
    "比想象",
    "很多人",
    "反差太大",
    "震惊",
    "崩了",
    "特大级消息",
    "变盘行情",
    "或迎",
    "周六上午传来",
)

GENERIC_TITLE_PATTERNS = {
    "图片新闻",
    "市场资讯",
}

ECON_QUALITY_TERMS = (
    "经济",
    "财经",
    "财政",
    "金融",
    "银行",
    "资本市场",
    "证券",
    "股票",
    "股市",
    "a股",
    "债券",
    "基金",
    "保险",
    "投资",
    "消费",
    "外贸",
    "进出口",
    "贸易",
    "产业",
    "制造业",
    "房地产",
    "就业",
    "民营",
    "企业",
    "市场",
    "gdp",
    "pmi",
    "新质生产力",
    "高质量发展",
)

OLD_SOURCE_ECON_TERMS = tuple(
    term for term in ECON_QUALITY_TERMS
    if term not in {"市场", "企业", "产业"}
)


def tokenize_for_rank(text: object) -> list[str]:
    value = str(text or "").casefold()
    tokens: list[str] = []
    for token in ASCII_TERM_RE.findall(value):
        if token not in tokens:
            tokens.append(token)
    for char in CJK_RE.findall(value):
        if char not in tokens:
            tokens.append(char)
    return tokens


def _candidate_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(field) or "") for field in ("title", "summary", "text", "source"))


def infer_publish_ts(item: dict[str, Any]) -> int:
    """Best-effort timestamp for legacy payloads that missed publish metadata."""
    raw_ts = item.get("publish_ts")
    try:
        if raw_ts:
            return int(float(raw_ts))
    except (TypeError, ValueError):
        pass

    for field in ("publish_time", "created_at", "date", "title"):
        text = str(item.get(field) or "")
        match = DATE_RE.search(text)
        if not match:
            continue
        year, month, day = (int(part) for part in match.groups())
        try:
            return int(datetime(year, month, day).timestamp())
        except ValueError:
            continue
    return 0


def normalize_publish_metadata(item: dict[str, Any]) -> dict[str, Any]:
    copy = dict(item)
    ts = infer_publish_ts(copy)
    if ts and not copy.get("publish_ts"):
        copy["publish_ts"] = ts
    if ts and not copy.get("publish_time"):
        copy["publish_time"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d 00:00:00")
    return copy


def lexical_score(query: object, item: dict[str, Any]) -> float:
    query_tokens = tokenize_for_rank(query)
    if not query_tokens:
        return 0.0
    candidate_tokens = set(tokenize_for_rank(_candidate_text(item)))
    if not candidate_tokens:
        return 0.0
    matched = sum(1 for token in query_tokens if token in candidate_tokens)
    return matched / len(query_tokens)


def quality_score(item: dict[str, Any]) -> float:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or item.get("text") or "")
    joined = f"{title} {summary[:160]}".lower()

    score = 1.0
    if not title.strip():
        score -= 0.55
    if len(summary.strip()) < 12:
        score -= 0.20
    if any(pattern.lower() in joined for pattern in ARTIFACT_PATTERNS):
        score -= 0.85
    clickbait_hits = sum(1 for pattern in CLICKBAIT_PATTERNS if pattern in title)
    if clickbait_hits:
        score -= min(0.75, 0.25 * clickbait_hits)
    if title.strip() in GENERIC_TITLE_PATTERNS:
        score -= 0.70
    if str(item.get("source") or "").lower() == "old" and not any(term in joined for term in OLD_SOURCE_ECON_TERMS):
        score -= 0.75
    if title.startswith("新闻联播") and not infer_publish_ts(item):
        score -= 0.20
    return max(0.05, min(1.0, score))


def recency_score(item: dict[str, Any], *, now_ts: float | None = None) -> float:
    ts = infer_publish_ts(item)
    if not ts:
        return 0.0
    now = now_ts if now_ts is not None else time.time()
    age_days = max(0.0, (now - ts) / 86400.0)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.95
    if age_days <= 90:
        return 0.80
    if age_days <= 180:
        return 0.60
    if age_days <= 365:
        return 0.45
    if age_days <= 365 * 3:
        return 0.20
    if age_days <= 365 * 10:
        return 0.05
    return 0.0


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [1.0 if high > 0 else 0.0 for _value in values]
    return [(value - low) / (high - low) for value in values]


def hybrid_rerank(
    query: object,
    items: list[dict[str, Any]],
    vector_weight: float = 0.7,
    lexical_weight: float = 0.3,
) -> list[dict[str, Any]]:
    if not items:
        return []

    vector_scores = [float(item.get("score") or 0.0) for item in items]
    lexical_scores = [lexical_score(query, item) for item in items]
    norm_vectors = _normalize(vector_scores)
    norm_lexical = _normalize(lexical_scores)

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        copy = dict(item)
        score = (vector_weight * norm_vectors[index]) + (lexical_weight * norm_lexical[index])
        copy["vector_score"] = vector_scores[index]
        copy["lexical_score"] = lexical_scores[index]
        copy["hybrid_score"] = score
        ranked.append(copy)

    ranked.sort(key=lambda item: (float(item["hybrid_score"]), float(item.get("score") or 0.0)), reverse=True)
    return ranked


def quality_aware_hybrid_rerank(
    query: object,
    items: list[dict[str, Any]],
    vector_weight: float = 0.62,
    lexical_weight: float = 0.28,
    quality_weight: float = 0.10,
) -> list[dict[str, Any]]:
    if not items:
        return []

    normalized_items = [normalize_publish_metadata(item) for item in items]
    vector_scores = [float(item.get("score") or 0.0) for item in normalized_items]
    lexical_scores = [lexical_score(query, item) for item in normalized_items]
    quality_scores = [quality_score(item) for item in normalized_items]
    norm_vectors = _normalize(vector_scores)
    norm_lexical = _normalize(lexical_scores)

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_items):
        copy = dict(item)
        score = (
            vector_weight * norm_vectors[index]
            + lexical_weight * norm_lexical[index]
            + quality_weight * quality_scores[index]
        )
        copy["vector_score"] = vector_scores[index]
        copy["lexical_score"] = lexical_scores[index]
        copy["quality_score"] = quality_scores[index]
        copy["hybrid_score"] = score
        ranked.append(copy)

    ranked.sort(key=lambda item: (float(item["hybrid_score"]), float(item.get("score") or 0.0)), reverse=True)
    return ranked


def time_aware_hybrid_rerank(
    query: object,
    items: list[dict[str, Any]],
    *,
    now_ts: float | None = None,
    vector_weight: float = 0.24,
    lexical_weight: float = 0.10,
    recency_weight: float = 0.58,
    quality_weight: float = 0.08,
) -> list[dict[str, Any]]:
    if not items:
        return []

    normalized_items = [normalize_publish_metadata(item) for item in items]
    vector_scores = [float(item.get("score") or 0.0) for item in normalized_items]
    lexical_scores = [lexical_score(query, item) for item in normalized_items]
    recency_scores = [recency_score(item, now_ts=now_ts) for item in normalized_items]
    quality_scores = [quality_score(item) for item in normalized_items]
    norm_vectors = _normalize(vector_scores)
    norm_lexical = _normalize(lexical_scores)

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_items):
        copy = dict(item)
        score = (
            vector_weight * norm_vectors[index]
            + lexical_weight * norm_lexical[index]
            + recency_weight * recency_scores[index]
            + quality_weight * quality_scores[index]
        )
        copy["vector_score"] = vector_scores[index]
        copy["lexical_score"] = lexical_scores[index]
        copy["recency_score"] = recency_scores[index]
        copy["quality_score"] = quality_scores[index]
        copy["hybrid_score"] = score
        ranked.append(copy)

    ranked.sort(
        key=lambda item: (
            float(item["hybrid_score"]),
            float(item.get("recency_score") or 0.0),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    return ranked
