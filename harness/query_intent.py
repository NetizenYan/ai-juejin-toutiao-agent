"""Intent-aware query analysis for hybrid retrieval (3.2-D).

Parses user query into structured intent signal used by the v2 retrieval
pipeline to decide which retrieval channels to activate and how to weight
merge/rerank.  Pure Python, no LLM call, no network — latency < 1 ms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Trigger vocabularies (shared with rag_query_router but extended)
# ---------------------------------------------------------------------------

_SOURCE_TRIGGERS = (
    "央视", "新闻联播", "新华社", "人民日报", "央视新闻",
    "中国日报", "经济日报", "证券时报", "财新",
)

_RECENT_SOFT_TRIGGERS = ("最近", "近期", "近来", "今年", "近段时间")
_RECENT_HARD_TRIGGERS = ("今天", "昨天", "本周", "现在")

_LIST_TRIGGERS = ("有哪些", "列举", "盘点", "汇总", "梳理", "哪些新闻", "哪些报道")

_CONTENT_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "commentary": ("评论员文章", "评论", "社论", "本报评论员"),
    "policy": ("政策", "意见", "规划", "方案", "通知", "指导意见", "措施"),
    "report": ("报告", "白皮书", "蓝皮书", "公报", "数据"),
    "news": ("新闻", "报道", "消息", "资讯", "头条"),
}

_ENTITY_TERMS = (
    "新质生产力", "高质量发展", "科技创新", "产业升级", "产业链",
    "制造业", "高技术制造业", "现代化产业体系", "先进制造",
    "半导体", "新能源", "数字经济", "人工智能", "房地产",
    "资本市场", "促消费", "外贸", "就业", "A股", "GDP", "PMI",
    "科技金融", "碳中和", "碳达峰", "乡村振兴", "共同富裕",
    "供应链", "芯片", "量子", "新型城镇化", "数据要素",
)

_STRIP_INSTRUCT_RE = re.compile(
    r"(帮我|请|麻烦|你能)?(查一下|查查|说说|介绍一下|解释一下|讲讲|分析一下|总结一下|看看)"
)
_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"(20[12]\d)\s*年")
_MONTH_RE = re.compile(r"(20[12]\d)\s*年\s*(\d{1,2})\s*月")
_DATE_RE = re.compile(r"(20[12]\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")
_SINCE_RE = re.compile(r"(\d{1,2})\s*月\s*(以来|左右)")
_CJK_TERM_RE = re.compile(r"[一-鿿]{2,}")

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
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class QueryIntent:
    original_query: str
    normalized_query: str
    query_type: str  # entity_search | source_search | time_search | topic_detail | general
    entities: list[str]
    source_constraint: list[str]
    source_aliases: list[str]
    date_constraint: dict[str, Any]
    content_type_hint: str  # commentary | policy | report | news | ""
    needs_recent: bool
    needs_list: bool
    hard_filters: dict[str, Any]
    soft_boosts: dict[str, Any]
    retrieval_plan: list[str]  # channels: dense, title_keyword, chunk_keyword

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "normalized_query": self.normalized_query,
            "query_type": self.query_type,
            "entities": self.entities,
            "source_constraint": self.source_constraint,
            "source_aliases": self.source_aliases,
            "date_constraint": self.date_constraint,
            "content_type_hint": self.content_type_hint,
            "needs_recent": self.needs_recent,
            "needs_list": self.needs_list,
            "hard_filters": self.hard_filters,
            "soft_boosts": self.soft_boosts,
            "retrieval_plan": self.retrieval_plan,
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _normalize(query: str) -> str:
    text = _WHITESPACE_RE.sub(" ", (query or "").strip())
    text = _STRIP_INSTRUCT_RE.sub("", text).strip()
    return text or (query or "").strip()


def _extract_entities(query: str) -> list[str]:
    entities: list[str] = []
    for term in _ENTITY_TERMS:
        if term in query and term not in entities:
            entities.append(term)
    for match in _CJK_TERM_RE.findall(query):
        if len(match) >= 3 and match not in entities:
            already = any(match in e or e in match for e in entities)
            if not already:
                entities.append(match)
    return entities[:15]


def _extract_sources(query: str) -> tuple[list[str], list[str]]:
    sources = [t for t in _SOURCE_TRIGGERS if t in (query or "")]
    aliases: list[str] = []
    for s in sources:
        for a in _SOURCE_ALIASES.get(s, (s,)):
            if a not in aliases:
                aliases.append(a)
    return sources, aliases


def _extract_date(query: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "has_explicit_date": False, "year": None, "month": None,
        "day": None, "since_month": None, "is_soft_recent": False,
    }
    dm = _DATE_RE.search(query)
    if dm:
        result.update({"has_explicit_date": True, "year": int(dm.group(1)),
                        "month": int(dm.group(2)), "day": int(dm.group(3))})
        return result
    mm = _MONTH_RE.search(query)
    if mm:
        result.update({"has_explicit_date": True, "year": int(mm.group(1)),
                        "month": int(mm.group(2))})
        return result
    ym = _YEAR_RE.search(query)
    if ym:
        result.update({"has_explicit_date": True, "year": int(ym.group(1))})
        return result
    sm = _SINCE_RE.search(query)
    if sm:
        result.update({"has_explicit_date": True, "since_month": int(sm.group(1))})
        return result
    if any(t in query for t in _RECENT_SOFT_TRIGGERS):
        result["is_soft_recent"] = True
    if any(t in query for t in _RECENT_HARD_TRIGGERS):
        result["is_soft_recent"] = True
    return result


def _detect_content_type(query: str) -> str:
    for ctype, triggers in _CONTENT_TYPE_HINTS.items():
        if any(t in query for t in triggers):
            return ctype
    return ""


def _detect_query_type(
    entities: list[str],
    sources: list[str],
    date: dict[str, Any],
    content_type: str,
) -> str:
    if sources:
        return "source_search"
    if date.get("has_explicit_date"):
        return "time_search"
    if entities:
        return "entity_search"
    if content_type:
        return "topic_detail"
    return "general"


def _build_retrieval_plan(
    query_type: str,
    entities: list[str],
    sources: list[str],
    needs_recent: bool,
    needs_list: bool,
) -> list[str]:
    """Decide which retrieval channels to activate.

    Always use dense.  Add keyword channels when there are entities or
    sources that the dense search might under-rank.
    """
    plan = ["dense"]
    if entities:
        plan.append("title_keyword")
        plan.append("chunk_keyword")
    if sources:
        plan.append("title_keyword")
    if needs_list or query_type in ("entity_search", "source_search"):
        if "chunk_keyword" not in plan:
            plan.append("chunk_keyword")
    return list(dict.fromkeys(plan))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_query_intent(query: str) -> QueryIntent:
    normalized = _normalize(query)
    entities = _extract_entities(normalized)
    sources, aliases = _extract_sources(normalized)
    date = _extract_date(normalized)
    content_type = _detect_content_type(normalized)
    needs_recent = date.get("is_soft_recent", False) or any(
        t in normalized for t in _RECENT_SOFT_TRIGGERS + _RECENT_HARD_TRIGGERS
    )
    needs_list = any(t in normalized for t in _LIST_TRIGGERS)
    query_type = _detect_query_type(entities, sources, date, content_type)

    hard_filters: dict[str, Any] = {}
    soft_boosts: dict[str, Any] = {}

    if sources:
        hard_filters["source"] = sources
    if date.get("has_explicit_date"):
        hard_filters["date"] = date
    if needs_recent:
        soft_boosts["recency"] = "soft_recent"
    if entities:
        soft_boosts["entities"] = entities
    if content_type:
        soft_boosts["content_type"] = content_type

    plan = _build_retrieval_plan(query_type, entities, sources, needs_recent, needs_list)

    return QueryIntent(
        original_query=query,
        normalized_query=normalized,
        query_type=query_type,
        entities=entities,
        source_constraint=sources,
        source_aliases=aliases,
        date_constraint=date,
        content_type_hint=content_type,
        needs_recent=needs_recent,
        needs_list=needs_list,
        hard_filters=hard_filters,
        soft_boosts=soft_boosts,
        retrieval_plan=plan,
    )
