"""Rule-based user query understanding for answer constraints.

This module extracts presentation constraints only. It does not decide auth,
tool access, or whether a retrieval tool may run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class UserQueryUnderstanding:
    raw_query: str
    style: str | None = None
    detail_level: str | None = None
    max_chars: int | None = None
    max_points: int | None = None
    must_include_citations: bool | None = None
    time_scope: str | None = None
    topics: list[str] = field(default_factory=list)


def _extract_max_chars(query: str) -> int | None:
    patterns = [
        r"(?:不超过|最多|控制在|限|限制在)\s*([0-9]{1,4})\s*字",
        r"([0-9]{1,4})\s*字\s*(?:以内|之内|内)",
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            return int(match.group(1))
    return None


def _extract_max_points(query: str) -> int | None:
    digit_match = re.search(r"(?:列|分|用)?\s*([0-9]{1,2})\s*点", query)
    if digit_match:
        return int(digit_match.group(1))

    cn_match = re.search(r"(?:列|分|用)?\s*([一二两三四五六七八九十])\s*点", query)
    if cn_match:
        return _CN_NUMBERS.get(cn_match.group(1))
    return None


def _extract_time_scope(query: str) -> str | None:
    if any(token in query for token in ("今天", "今日")):
        return "today"
    if "昨天" in query:
        return "yesterday"
    if "本周" in query:
        return "this_week"
    if "上个月" in query:
        return "last_month"
    if "今年" in query:
        return "this_year"
    if any(token in query for token in ("最近", "近期", "最新", "现在")):
        return "recent"
    return None


def understand_user_query(query: str) -> UserQueryUnderstanding:
    q = (query or "").strip()
    style = None
    detail_level = None

    if any(token in q for token in ("简单说说", "通俗点", "通俗一点", "总结一下", "简单讲", "讲明白")):
        style = "plain_language"
        detail_level = "brief"

    if any(token in q for token in ("详细分析", "展开说", "详细说", "深入分析")):
        detail_level = "detail"

    must_include_citations = None
    if any(token in q for token in ("不用引用", "不要引用", "不带引用", "无需引用")):
        must_include_citations = False
    elif any(token in q for token in ("保留引用", "带新闻证据", "保留新闻证据", "带引用", "引用新闻", "证据引用")):
        must_include_citations = True

    return UserQueryUnderstanding(
        raw_query=q,
        style=style,
        detail_level=detail_level,
        max_chars=_extract_max_chars(q),
        max_points=_extract_max_points(q),
        must_include_citations=must_include_citations,
        time_scope=_extract_time_scope(q),
        topics=[],
    )
