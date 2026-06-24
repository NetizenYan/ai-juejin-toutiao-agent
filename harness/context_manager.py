"""Conversation context assembly for the news agent.

Memory v1 is deliberately conservative: it keeps short-term conversation shape,
presentation constraints, and recent evidence ids for pronoun resolution. It
never turns previous conversation or old evidence ids into factual evidence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from harness.query_understanding import UserQueryUnderstanding


SUMMARY_KEYS = (
    "user_goal",
    "confirmed_topics",
    "active_constraints",
    "open_questions",
    "last_valid_state",
    "last_route",
    "last_evidence_ids",
    "relevant_preferences",
)

_NEWS_REF_RE = re.compile(r"\[?(news:[A-Za-z0-9_\-:]+)\]?")
_MAX_CHARS_PATTERNS = (
    re.compile(r"(?:不超过|最多|控制在|限|限制在)\s*([0-9]{1,4})\s*字"),
    re.compile(r"([0-9]{1,4})\s*字\s*(?:以内|之内|内)"),
)
_MAX_POINTS_PATTERNS = (
    re.compile(r"(?:最多|列|分|用)?\s*([0-9]{1,2})\s*点"),
)
_TOPIC_KEYWORDS = (
    "新质生产力",
    "高质量发展",
    "财政政策",
    "货币政策",
    "宏观政策",
    "制造业",
    "先进制造",
    "产业链",
    "半导体",
    "房地产",
    "资本市场",
    "促消费",
    "新能源",
    "外贸",
    "就业",
    "数字经济",
    "人工智能",
    "科技创新",
    "产业升级",
    "现代化产业体系",
    "A股",
)
_SOURCE_KEYWORDS = (
    "经济日报",
    "人民日报",
    "新闻联播",
    "央视",
    "央视新闻",
    "新华社",
)
_FOLLOW_UP_MARKERS = (
    "它",
    "这个",
    "那个",
    "那这",
    "这和",
    "这对",
    "刚才",
    "上面",
    "前面",
    "上一轮",
    "这条",
    "该政策",
    "这件事",
    "这些",
    "这种",
    "这类",
    "该类",
)
_FOLLOW_UP_PRONOUN_PATTERNS = (
    re.compile(r"刚才那个"),
    re.compile(r"那这个"),
    re.compile(r"那它"),
    re.compile(r"那这"),
    re.compile(r"这个"),
    re.compile(r"那个"),
    re.compile(r"这些"),
    re.compile(r"这种"),
    re.compile(r"这类"),
    re.compile(r"该类"),
)
_GENERATION_INSTRUCTION_PATTERNS = (
    re.compile(r"请"),
    re.compile(r"简单说说?"),
    re.compile(r"简单讲"),
    re.compile(r"简短(?:回答|说明)?"),
    re.compile(r"通俗(?:点|一点)?"),
    re.compile(r"带引用"),
    re.compile(r"保留(?:新闻证据)?引用"),
    re.compile(r"新闻证据引用"),
    re.compile(r"回答一下"),
    re.compile(r"(?:用)?不超过\s*[0-9]{1,4}\s*字(?:回答)?"),
    re.compile(r"[0-9]{1,4}\s*字\s*(?:以内|之内|内)"),
    re.compile(r"只看"),
    re.compile(r"综合说明"),
    re.compile(r"分别说明"),
)
_CONTEXT_ANCHOR_PATTERNS = (
    re.compile(r"(?:^|[，。！？?\n])(?:请问|请|帮我看看|帮我看下|帮我|只看|看看|看一下|关于)?\s*([^，。！？?\n]{2,50}?)(?:这篇|这条)?(?:报道|文章|新闻)"),
    re.compile(r"(?:^|[，。！？?\n])(?:请问|请|帮我看看|帮我看下|帮我|只看|看看|看一下|关于)?\s*([^，。！？?\n]{2,50}?)(?:有什么|有哪些)(?:报道|文章|新闻)"),
)
_CONTEXT_ANCHOR_PREFIX_RE = re.compile(r"^(?:请问|请|帮我看看|帮我看下|帮我|只看|看看|看一下|关于|最近)\s*")
_CONTEXT_ANCHOR_SUFFIX_RE = re.compile(r"(?:这篇|这条)$")
_WEAK_CONTEXT_ANCHORS = {"它", "这个", "那个", "这篇", "这条", "该报道", "该新闻", "该文章"}


@dataclass
class SessionContext:
    recent_messages: list[dict[str, str]]
    session_summary: dict[str, Any] | None
    active_constraints: dict[str, Any] = field(default_factory=dict)
    last_route: str | None = None
    last_evidence_ids: list[str] = field(default_factory=list)
    contextual_anchors: list[str] = field(default_factory=list)
    long_context_memory: dict[str, Any] | None = None
    topic_ledger: list[dict[str, Any]] = field(default_factory=list)
    anchor_ledger: list[dict[str, Any]] = field(default_factory=list)
    constraint_ledger: list[dict[str, Any]] = field(default_factory=list)
    evidence_ledger: list[dict[str, Any]] = field(default_factory=list)
    ledger_state: dict[str, Any] = field(default_factory=dict)
    user_preferences: dict[str, Any] = field(default_factory=dict)
    compression_triggered: bool = False
    memory_is_evidence: bool = False

    def to_metadata(self) -> dict[str, Any]:
        return {
            "type": "session_summary",
            "use_as_evidence": False,
            "summary": self.session_summary,
            "active_constraints": self.active_constraints,
            "last_route": self.last_route,
            "last_evidence_ids": self.last_evidence_ids,
            "contextual_anchors": self.contextual_anchors,
            "long_context_memory": self.long_context_memory,
            "topic_ledger": self.topic_ledger,
            "anchor_ledger": self.anchor_ledger,
            "constraint_ledger": self.constraint_ledger,
            "evidence_ledger": self.evidence_ledger,
            "ledger_state": self.ledger_state,
            "user_preferences": self.user_preferences,
            "compression_triggered": self.compression_triggered,
        }


def _message_content(message: dict[str, Any]) -> str:
    return str(message.get("content") or "")


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = _message_content(message).strip()
        if role not in {"system", "user", "assistant"} or not content:
            continue
        sanitized.append({"role": role, "content": content})
    return sanitized


def _truncate(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _total_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(_message_content(message)) for message in messages)


def should_compress_context(
    messages: list[dict[str, Any]],
    *,
    message_threshold: int = 12,
    char_threshold: int = 6000,
    context_budget_chars: int | None = None,
    estimated_output_chars: int = 1200,
) -> bool:
    if len(messages) > message_threshold:
        return True
    total_chars = _total_chars(messages)
    if total_chars > char_threshold:
        return True
    if context_budget_chars and total_chars + estimated_output_chars > context_budget_chars * 0.6:
        return True
    return False


def _extract_max_chars(text: str) -> int | None:
    for pattern in _MAX_CHARS_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _extract_max_points(text: str) -> int | None:
    for pattern in _MAX_POINTS_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _constraints_from_text(text: str) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    if any(token in text for token in ("简单点", "简单说", "简短", "简洁", "通俗点", "通俗一点", "别太长")):
        constraints["style"] = "plain_language"
        constraints["detail_level"] = "brief"
    if any(token in text for token in ("详细分析", "展开说", "详细说", "深入分析")):
        constraints["detail_level"] = "detail"

    max_chars = _extract_max_chars(text)
    if max_chars is not None:
        constraints["max_chars"] = max_chars

    max_points = _extract_max_points(text)
    if max_points is not None:
        constraints["max_points"] = max_points

    if any(token in text for token in ("不用引用", "不要引用", "不带引用", "无需引用")):
        constraints["must_include_citations"] = False
    elif any(token in text for token in ("保留引用", "带引用", "引用新闻", "新闻证据", "证据引用")):
        constraints["must_include_citations"] = True

    if any(token in text for token in ("不要股票预测", "不需要股票预测", "不要投资建议", "不做投资建议")):
        constraints["no_stock_prediction"] = True
    return constraints


def extract_active_constraints(messages: list[dict[str, Any]]) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for message in messages:
        if message.get("role") != "user":
            continue
        constraints.update(_constraints_from_text(_message_content(message)))
    return constraints


def _extract_user_preferences(messages: list[dict[str, Any]]) -> dict[str, Any]:
    preferences: dict[str, Any] = {}
    user_text = "\n".join(_message_content(message) for message in messages if message.get("role") == "user")
    if any(token in user_text for token in ("简单点", "简短", "简洁", "通俗点")):
        preferences["brief_answers"] = True
    if any(token in user_text for token in ("保留引用", "带引用", "新闻证据", "证据引用")):
        preferences["prefer_citations"] = True
    if any(token in user_text for token in ("经济", "财经", "政策", "宏观", "新质生产力", "高质量发展")):
        preferences["focus_domains"] = ["economy_policy"]
    if any(token in user_text for token in ("不要股票预测", "不需要股票预测", "不要投资建议", "不做投资建议")):
        preferences["no_stock_prediction"] = True
    return preferences


def _extract_topics(messages: list[dict[str, Any]]) -> list[str]:
    text = "\n".join(_message_content(message) for message in messages if message.get("role") == "user")
    topics: list[str] = []
    for topic in _TOPIC_KEYWORDS:
        if topic in text and topic not in topics:
            topics.append(topic)
    return topics


def _extract_sources(messages: list[dict[str, Any]]) -> list[str]:
    text = "\n".join(_message_content(message) for message in messages if message.get("role") == "user")
    sources: list[str] = []
    for source in _SOURCE_KEYWORDS:
        if source in text and source not in sources:
            sources.append(source)
    return sources


def _turn_index_for_message(index: int) -> int:
    return index // 2 + 1


def _extract_time_terms(text: str) -> list[str]:
    terms: list[str] = []
    for pattern in (
        re.compile(r"20[12]\d\s*年\s*\d{1,2}\s*月"),
        re.compile(r"20[12]\d\s*年"),
        re.compile(r"(?:今天|昨天|近期|最近|今年|本周)"),
    ):
        for match in pattern.findall(text or ""):
            value = str(match)
            if value not in terms:
                terms.append(value)
    return terms


def _build_topic_ledger(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        content = _message_content(message)
        topics = [topic for topic in _TOPIC_KEYWORDS if topic in content]
        sources = [source for source in _SOURCE_KEYWORDS if source in content]
        if not topics and not sources:
            continue
        ledger.append({
            "topic_id": f"topic:{len(ledger) + 1}",
            "first_turn_index": _turn_index_for_message(index),
            "last_mentioned_turn_index": _turn_index_for_message(index),
            "topic_terms": topics,
            "source_terms": sources,
            "time_terms": _extract_time_terms(content),
            "related_anchor_ids": [],
        })
    return ledger


def _build_anchor_ledger(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, message in enumerate(messages):
        evidence = message.get("evidence")
        if not isinstance(evidence, dict):
            continue
        anchor = evidence.get("confirmed_anchor")
        if not isinstance(anchor, dict):
            continue
        anchor_id = str(anchor.get("anchor_id") or anchor.get("evidence_id") or "").strip()
        if not anchor_id or anchor_id in seen:
            continue
        seen.add(anchor_id)
        ledger.append({
            "anchor_id": anchor_id,
            "title": str(anchor.get("title") or ""),
            "source_name": str(anchor.get("source_name") or ""),
            "evidence_id_or_url": str(anchor.get("source_url") or anchor_id),
            "match_confidence": "confirmed",
            "source_credibility": str(anchor.get("source_credibility") or "unknown"),
            "verification_status": str(anchor.get("verification_status") or "unknown"),
            "acquisition_method": str(anchor.get("acquisition_method") or "unknown"),
            "user_confirmed": True,
            "confirmed_turn_index": _turn_index_for_message(index),
        })
        external_verification = anchor.get("external_verification")
        if isinstance(external_verification, dict) and external_verification:
            ledger[-1]["external_verification"] = dict(external_verification)
    return ledger


def _build_constraint_ledger(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        constraints = _constraints_from_text(_message_content(message))
        for key, value in constraints.items():
            ledger.append({
                "constraint_id": f"constraint:{len(ledger) + 1}",
                "scope": key,
                "value": value,
                "source_turn_index": _turn_index_for_message(index),
            })
    return ledger


def _build_evidence_ledger(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, message in enumerate(messages):
        for ref in _NEWS_REF_RE.findall(_message_content(message)):
            if ref in seen:
                continue
            seen.add(ref)
            ledger.append({
                "evidence_ref": ref,
                "anchor_id": "",
                "source_type": "station_internal",
                "retrieval_turn_index": _turn_index_for_message(index),
                "credibility_label": "high",
                "validation_notes": "",
            })
    return ledger


def _build_long_context_memory(
    messages: list[dict[str, Any]],
    recent_messages: list[dict[str, str]],
    *,
    max_chars: int,
    message_char_limit: int,
) -> dict[str, Any] | None:
    if not messages:
        return None
    recent_contents = {message["content"] for message in recent_messages}
    older = [message for message in messages if _message_content(message) not in recent_contents]
    compressed: list[dict[str, str]] = []
    estimated = 0
    for message in older:
        content = _truncate(_message_content(message), message_char_limit)
        if not content:
            continue
        if estimated + len(content) > max_chars:
            break
        estimated += len(content)
        compressed.append({"role": str(message.get("role") or ""), "content": content})
    if not compressed:
        return None
    return {
        "use_as_evidence": False,
        "source_message_count": len(messages),
        "compressed_message_count": len(compressed),
        "estimated_chars": estimated,
        "compressed_messages": compressed,
    }


def _compact_context_anchor(anchor: str) -> str:
    value = re.sub(r"\s+", " ", anchor or "").strip(" ，。！？?、")
    value = _CONTEXT_ANCHOR_PREFIX_RE.sub("", value).strip(" ，。！？?、")
    value = _CONTEXT_ANCHOR_SUFFIX_RE.sub("", value).strip(" ，。！？?、")
    return value[:50].strip()


def _extract_contextual_anchors(messages: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    anchors: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = _message_content(message)
        for pattern in _CONTEXT_ANCHOR_PATTERNS:
            for match in pattern.finditer(content):
                anchor = _compact_context_anchor(match.group(1))
                signal = re.sub(r"[\s，。！？?、]", "", anchor)
                if len(signal) < 4 or anchor in _WEAK_CONTEXT_ANCHORS:
                    continue
                if anchor not in anchors:
                    anchors.append(anchor)
    return anchors[-limit:]


def clean_retrieval_query(query: str) -> str:
    """Remove answer-format instructions while preserving retrieval constraints."""
    cleaned = (query or "").strip()
    for pattern in _GENERATION_INSTRUCTION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"[，,、]\s*[，,、]+", "，", cleaned)
    cleaned = re.sub(r"[，,、]\s*[。.]", "。", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^[，,、。.\s]+|[，,、。.\s]+$", "", cleaned)
    return cleaned.strip()


def extract_last_evidence_ids(messages: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    evidence_ids: list[str] = []
    for message in messages:
        evidence = message.get("evidence")
        if isinstance(evidence, dict):
            for ref in evidence.get("refs") or []:
                if isinstance(ref, str) and ref.startswith("news:") and ref not in evidence_ids:
                    evidence_ids.append(ref)
        for ref in _NEWS_REF_RE.findall(_message_content(message)):
            if ref not in evidence_ids:
                evidence_ids.append(ref)
    return evidence_ids[-limit:]


def _constraints_to_list(constraints: dict[str, Any]) -> list[str]:
    entries: list[str] = []
    if constraints.get("style"):
        entries.append(f"style={constraints['style']}")
    if constraints.get("detail_level"):
        entries.append(f"detail_level={constraints['detail_level']}")
    if constraints.get("max_chars"):
        entries.append(f"max_chars={constraints['max_chars']}")
    if constraints.get("max_points"):
        entries.append(f"max_points={constraints['max_points']}")
    if constraints.get("must_include_citations") is not None:
        entries.append(f"must_include_citations={constraints['must_include_citations']}")
    if constraints.get("no_stock_prediction"):
        entries.append("no_stock_prediction=True")
    return entries


def _preferences_to_list(preferences: dict[str, Any]) -> list[str]:
    entries: list[str] = []
    for key, value in preferences.items():
        entries.append(f"{key}={value}")
    return entries


def _latest_user_goal(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _truncate(_message_content(message))
    return ""


def _open_questions(messages: list[dict[str, Any]]) -> list[str]:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = _message_content(message)
            if any(mark in content for mark in ("?", "？", "什么", "怎么", "是否", "有没有")):
                return [_truncate(content)]
            return []
    return []


def _build_summary(
    messages: list[dict[str, Any]],
    *,
    active_constraints: dict[str, Any],
    last_evidence_ids: list[str],
    user_preferences: dict[str, Any],
    last_route: str | None,
) -> dict[str, Any]:
    return {
        "user_goal": _latest_user_goal(messages),
        "confirmed_topics": _extract_topics(messages),
        "active_constraints": _constraints_to_list(active_constraints),
        "open_questions": _open_questions(messages),
        "last_valid_state": {},
        "last_route": last_route or "",
        "last_evidence_ids": last_evidence_ids,
        "relevant_preferences": _preferences_to_list(user_preferences),
    }


def _merge_summary_lists(previous: Any, current: Any, *, limit: int = 80) -> list[Any]:
    merged: list[Any] = []
    for value in [*(previous or []), *(current or [])]:
        if _is_empty_value(value):
            continue
        if value not in merged:
            merged.append(value)
    return merged[-limit:]


def _merge_summary_with_previous(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(previous, dict):
        return current
    merged = dict(current)
    for key in ("confirmed_topics", "active_constraints", "last_evidence_ids", "relevant_preferences"):
        merged[key] = _merge_summary_lists(previous.get(key), current.get(key))
    previous_state = previous.get("last_valid_state") if isinstance(previous.get("last_valid_state"), dict) else {}
    current_state = current.get("last_valid_state") if isinstance(current.get("last_valid_state"), dict) else {}
    merged["last_valid_state"] = {**previous_state, **current_state}
    if not merged.get("last_route"):
        merged["last_route"] = previous.get("last_route") or ""
    return merged


def _normalize_previous_summary(previous_summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(previous_summary, dict):
        return None
    summary = previous_summary.get("summary") if "summary" in previous_summary else previous_summary
    if not isinstance(summary, dict):
        return None
    normalized = {key: summary.get(key, [] if key.endswith("s") else "") for key in SUMMARY_KEYS}
    if not isinstance(normalized["last_valid_state"], dict):
        normalized["last_valid_state"] = {}
    return normalized


def _previous_context_metadata(previous_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(previous_summary, dict):
        return {}
    context = previous_summary.get("context")
    if isinstance(context, dict):
        return context
    return previous_summary


def _ledger_entries(context: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = context.get(key)
    if not isinstance(values, list):
        return []
    return [dict(value) for value in values if isinstance(value, dict)]


def _dedupe_strings(values: list[Any], *, limit: int) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value not in deduped:
            deduped.append(value)
    return deduped[-limit:]


def _merge_term_list(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *incoming]:
        if isinstance(value, str) and value and value not in merged:
            merged.append(value)
    return merged


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _topic_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    topics = tuple(sorted(str(value) for value in entry.get("topic_terms") or [] if isinstance(value, str)))
    sources = tuple(sorted(str(value) for value in entry.get("source_terms") or [] if isinstance(value, str)))
    times = tuple(sorted(str(value) for value in entry.get("time_terms") or [] if isinstance(value, str)))
    if topics or sources or times:
        return topics, sources, times
    return ("topic_id", str(entry.get("topic_id") or ""))


def _merge_topic_entries(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key in ("topic_terms", "source_terms", "time_terms", "related_anchor_ids"):
        merged[key] = _merge_term_list(list(merged.get(key) or []), list(incoming.get(key) or []))
    existing_first = _safe_int(merged.get("first_turn_index"), 0)
    incoming_first = _safe_int(incoming.get("first_turn_index"), 0)
    if incoming_first and (not existing_first or incoming_first < existing_first):
        merged["first_turn_index"] = incoming_first
    existing_last = _safe_int(merged.get("last_mentioned_turn_index"), 0)
    incoming_last = _safe_int(incoming.get("last_mentioned_turn_index"), 0)
    if incoming_last > existing_last:
        merged["last_mentioned_turn_index"] = incoming_last
    return merged


def _merge_topic_ledgers(previous: list[dict[str, Any]], current: list[dict[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[Any, ...], int] = {}
    for entry in [*previous, *current]:
        key = _topic_key(entry)
        if key in index_by_key:
            merged[index_by_key[key]] = _merge_topic_entries(merged[index_by_key[key]], entry)
            continue
        copied = dict(entry)
        copied.setdefault("topic_id", f"topic:{len(merged) + 1}")
        merged.append(copied)
        index_by_key[key] = len(merged) - 1
    return merged[-limit:]


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_dict_values(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if _is_empty_value(value):
            continue
        if key == "external_verification" and isinstance(value, dict):
            prior = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = {**prior, **value}
            continue
        if key == "user_confirmed":
            merged[key] = bool(merged.get(key)) or bool(value)
            continue
        if key in {"confirmed_turn_index", "retrieval_turn_index", "source_turn_index"}:
            prior_int = _safe_int(merged.get(key), 0)
            value_int = _safe_int(value, 0)
            merged[key] = min(prior_int, value_int) if prior_int and value_int else (prior_int or value_int)
            continue
        if _is_empty_value(merged.get(key)):
            merged[key] = value
    return merged


def _merge_keyed_ledgers(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    key_field: str,
    limit: int = 80,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for entry in [*previous, *current]:
        key = str(entry.get(key_field) or "").strip()
        if not key:
            continue
        if key in index_by_key:
            merged[index_by_key[key]] = _merge_dict_values(merged[index_by_key[key]], entry)
            continue
        merged.append(dict(entry))
        index_by_key[key] = len(merged) - 1
    return merged[-limit:]


def _constraint_key(entry: dict[str, Any]) -> str:
    return f"{entry.get('scope')}={entry.get('value')}"


def _merge_constraint_ledgers(previous: list[dict[str, Any]], current: list[dict[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in [*previous, *current]:
        key = _constraint_key(entry)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(dict(entry))
    return merged[-limit:]


def _previous_last_evidence_ids(previous_context: dict[str, Any], normalized_summary: dict[str, Any] | None) -> list[str]:
    values: list[Any] = []
    if isinstance(normalized_summary, dict):
        values.extend(normalized_summary.get("last_evidence_ids") or [])
    values.extend(previous_context.get("last_evidence_ids") or [])
    return _dedupe_strings(values, limit=80)


def _build_ledger_state(
    previous_context: dict[str, Any],
    *,
    topic_ledger: list[dict[str, Any]],
    anchor_ledger: list[dict[str, Any]],
    evidence_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    previous_counts = {
        key: len(previous_context.get(key) or []) if isinstance(previous_context.get(key), list) else 0
        for key in ("topic_ledger", "anchor_ledger", "constraint_ledger", "evidence_ledger")
    }
    incremental = any(previous_counts.values()) or bool(previous_context.get("last_evidence_ids"))
    return {
        "use_as_evidence": False,
        "merge_strategy": "previous_context_incremental" if incremental else "current_history_scan",
        "previous_counts": previous_counts,
        "topic_count": len(topic_ledger),
        "anchor_count": len(anchor_ledger),
        "evidence_count": len(evidence_ledger),
    }


def build_session_context(
    history_messages: list[dict[str, Any]],
    *,
    recent_turns: int = 6,
    message_threshold: int = 12,
    char_threshold: int = 6000,
    session_summary_enabled: bool = True,
    previous_summary: dict[str, Any] | None = None,
    last_route: str | None = None,
    max_recent_evidence_ids: int = 8,
    context_budget_chars: int | None = None,
    long_context_max_chars: int = 1800,
    long_context_message_char_limit: int = 160,
) -> SessionContext:
    messages = _sanitize_messages(history_messages)
    recent_limit = max(1, recent_turns) * 2
    recent_messages = messages[-recent_limit:]
    active_constraints = extract_active_constraints(messages)
    user_preferences = _extract_user_preferences(messages)
    last_evidence_ids = extract_last_evidence_ids(history_messages, limit=max_recent_evidence_ids)
    contextual_anchors = _extract_contextual_anchors(messages, limit=6)
    topic_ledger = _build_topic_ledger(messages)
    anchor_ledger = _build_anchor_ledger(history_messages)
    constraint_ledger = _build_constraint_ledger(messages)
    evidence_ledger = _build_evidence_ledger(history_messages)
    previous_context = _previous_context_metadata(previous_summary)
    normalized_previous = _normalize_previous_summary(previous_summary)
    previous_evidence_ids = _previous_last_evidence_ids(previous_context, normalized_previous)
    if previous_evidence_ids:
        last_evidence_ids = _dedupe_strings(
            [*previous_evidence_ids, *last_evidence_ids],
            limit=max_recent_evidence_ids,
        )
    contextual_anchors = _dedupe_strings(
        [*(previous_context.get("contextual_anchors") or []), *contextual_anchors],
        limit=6,
    )
    topic_ledger = _merge_topic_ledgers(
        _ledger_entries(previous_context, "topic_ledger"),
        topic_ledger,
    )
    anchor_ledger = _merge_keyed_ledgers(
        _ledger_entries(previous_context, "anchor_ledger"),
        anchor_ledger,
        key_field="anchor_id",
    )
    constraint_ledger = _merge_constraint_ledgers(
        _ledger_entries(previous_context, "constraint_ledger"),
        constraint_ledger,
    )
    evidence_ledger = _merge_keyed_ledgers(
        _ledger_entries(previous_context, "evidence_ledger"),
        evidence_ledger,
        key_field="evidence_ref",
    )
    ledger_state = _build_ledger_state(
        previous_context,
        topic_ledger=topic_ledger,
        anchor_ledger=anchor_ledger,
        evidence_ledger=evidence_ledger,
    )
    compression_triggered = should_compress_context(
        messages,
        message_threshold=message_threshold,
        char_threshold=char_threshold,
        context_budget_chars=context_budget_chars,
    )

    session_summary = normalized_previous
    if session_summary_enabled:
        session_summary = _build_summary(
            messages,
            active_constraints=active_constraints,
            last_evidence_ids=last_evidence_ids,
            user_preferences=user_preferences,
            last_route=last_route,
        )
        session_summary = _merge_summary_with_previous(session_summary, normalized_previous)
    long_context_memory = (
        _build_long_context_memory(
            messages,
            recent_messages,
            max_chars=max(1, long_context_max_chars),
            message_char_limit=max(1, long_context_message_char_limit),
        )
        if compression_triggered
        else None
    )

    return SessionContext(
        recent_messages=recent_messages,
        session_summary=session_summary,
        active_constraints=active_constraints,
        last_route=last_route,
        last_evidence_ids=last_evidence_ids,
        contextual_anchors=contextual_anchors,
        long_context_memory=long_context_memory,
        topic_ledger=topic_ledger,
        anchor_ledger=anchor_ledger,
        constraint_ledger=constraint_ledger,
        evidence_ledger=evidence_ledger,
        ledger_state=ledger_state,
        user_preferences=user_preferences,
        compression_triggered=compression_triggered,
        memory_is_evidence=False,
    )


def apply_context_constraints(
    understanding: UserQueryUnderstanding,
    active_constraints: dict[str, Any],
) -> UserQueryUnderstanding:
    if not active_constraints:
        return understanding
    must_include_citations = understanding.must_include_citations
    if must_include_citations is None and "must_include_citations" in active_constraints:
        must_include_citations = bool(active_constraints["must_include_citations"])

    return replace(
        understanding,
        style=understanding.style or active_constraints.get("style"),
        detail_level=understanding.detail_level or active_constraints.get("detail_level"),
        max_chars=understanding.max_chars or active_constraints.get("max_chars"),
        max_points=understanding.max_points or active_constraints.get("max_points"),
        must_include_citations=must_include_citations,
    )


def is_contextual_follow_up(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _FOLLOW_UP_MARKERS)


def build_contextual_retrieval_query(query: str, context: SessionContext | None) -> str:
    """Expand pronoun follow-ups for retrieval only.

    This does not create evidence. It only helps the next retrieve_news call ask
    for the current turn's evidence with the previous topic made explicit.
    """
    clean_query = clean_retrieval_query(query)
    if not clean_query or context is None or not is_contextual_follow_up(clean_query):
        return clean_query

    stripped_query = clean_query
    for pattern in _FOLLOW_UP_PRONOUN_PATTERNS:
        stripped_query = pattern.sub("", stripped_query)
    stripped_query = re.sub(r"^[，,、。.\s]+|[，,、。.\s]+$", "", stripped_query).strip()
    stripped_signal = re.sub(r"[\s，,、。.！!？?]+", "", stripped_query)
    if stripped_query and len(stripped_signal) >= 6:
        clean_query = stripped_query

    hints: list[str] = []
    for anchor in context.contextual_anchors:
        if not isinstance(anchor, str) or not anchor:
            continue
        hint = anchor if any(token in anchor for token in ("报道", "文章", "新闻")) else f"{anchor} 报道"
        if hint not in hints:
            hints.append(hint)
    summary = context.session_summary or {}
    for topic in summary.get("confirmed_topics") or []:
        if isinstance(topic, str) and topic not in hints:
            hints.append(topic)
    for entry in context.topic_ledger:
        if not isinstance(entry, dict):
            continue
        for source in entry.get("source_terms") or []:
            if isinstance(source, str) and source not in hints:
                hints.append(source)
        for topic in entry.get("topic_terms") or []:
            if isinstance(topic, str) and topic not in hints:
                hints.append(topic)
    for anchor in context.anchor_ledger:
        if not isinstance(anchor, dict):
            continue
        title = anchor.get("title")
        if isinstance(title, str) and title and title not in hints:
            hints.append(title)
    for source in _extract_sources(context.recent_messages):
        if source not in hints:
            hints.append(source)
    for topic in _extract_topics(context.recent_messages):
        if topic not in hints:
            hints.append(topic)

    if not hints:
        return clean_query
    hint_prefix = " ".join(hints[:6])
    return f"{hint_prefix} {clean_query}"


def render_session_context_section(context: SessionContext) -> str:
    payload = {
        "summary": context.session_summary,
        "active_constraints": context.active_constraints,
        "user_preferences": context.user_preferences,
        "last_route": context.last_route,
        "last_evidence_ids": context.last_evidence_ids,
        "contextual_anchors": context.contextual_anchors,
        "topic_ledger": context.topic_ledger,
        "anchor_ledger": context.anchor_ledger,
        "constraint_ledger": context.constraint_ledger,
        "evidence_ledger": context.evidence_ledger,
        "ledger_state": context.ledger_state,
        "memory_policy": (
            "会话摘要和最近 evidence id 仅用于理解指代、用户偏好和回答约束；"
            "不可作为新闻事实来源。新闻事实只能来自本轮 evidence_pack。"
        ),
    }
    recent_messages = [
        {"role": message["role"], "content": _truncate(message["content"], 500)}
        for message in context.recent_messages
    ]
    return (
        '<session_context use_as_evidence="false">\n'
        "这里是会话摘要和短期记忆，只用于理解上下文、指代和用户约束，"
        "不可作为新闻事实来源。\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "</session_context>\n\n"
        + (
            '<long_context_memory use_as_evidence="false">\n'
            "Long context memory is not factual evidence; it only preserves topics, anchors, constraints, and references.\n"
            f"{json.dumps(context.long_context_memory, ensure_ascii=False, indent=2)}\n"
            "</long_context_memory>\n\n"
            if context.long_context_memory
            else ""
        )
        + "<recent_messages>\n"
        "最近 4-6 轮原文如下；仍不得把历史回答当作新闻事实证据。\n"
        f"{json.dumps(recent_messages, ensure_ascii=False, indent=2)}\n"
        "</recent_messages>\n"
        "如果 evidence_pack 不支持用户问题，必须拒答或说明未找到可靠证据。"
    )
