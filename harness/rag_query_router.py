"""Query routing policy for cautious news RAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_DETAIL_TRIGGERS = (
    "具体内容",
    "有哪些内容",
    "有哪内容",
    "说了什么",
    "提到",
    "原因",
    "影响",
    "措施",
    "数据",
    "进展",
    "细节",
    "为什么",
    "怎么做",
    "内容",
)

TIMELINE_RECENT_TRIGGERS = (
    "最近",
    "近期",
    "近来",
    "近段时间",
    "今天",
    "昨天",
    "本周",
    "今年",
    "最新",
    "时间线",
    "后来",
    "现在",
    "进展",
)

SOURCE_TRIGGERS = (
    "央视",
    "新闻联播",
    "新华社",
    "人民日报",
    "央视新闻",
    "中国日报",
    "经济日报",
    "证券时报",
    "财新",
)

ECON_FINANCE_TRIGGERS = (
    "经济",
    "财经",
    "财政",
    "宏观政策",
    "宏观",
    "补贴",
    "金融",
    "银行",
    "货币",
    "央行",
    "资本市场",
    "证券",
    "股票",
    "股市",
    "债券",
    "基金",
    "保险",
    "投资",
    "消费",
    "外贸",
    "进出口",
    "出口",
    "进口",
    "贸易",
    "产业",
    "产业升级",
    "制造业",
    "房地产",
    "楼市",
    "就业",
    "民营",
    "企业",
    "市场",
    "GDP",
    "生产总值",
    "PMI",
    "科技金融",
    "高质量发展",
    "新质生产力",
    "新动能",
    "科技创新",
    "创新驱动",
    "现代化产业体系",
)


@dataclass(frozen=True)
class RagRoute:
    query_type: str
    retrieval_strategy: str
    body_fallback_slots: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "query_type": self.query_type,
            "retrieval_strategy": self.retrieval_strategy,
            "body_fallback_slots": self.body_fallback_slots,
            "reason": self.reason,
        }


def _contains_any(query: str, triggers: tuple[str, ...]) -> bool:
    return any(trigger in query for trigger in triggers)


def route_rag_query(
    query: str,
    *,
    enabled: bool = True,
    default_body_fallback_slots: int = 0,
) -> RagRoute:
    """Return a deterministic RAG route for a user query."""
    safe_default_slots = max(0, int(default_body_fallback_slots or 0))
    if not enabled:
        return RagRoute(
            query_type="title_or_entity",
            retrieval_strategy="summary_first",
            body_fallback_slots=safe_default_slots,
            reason="query router disabled",
        )

    normalized = (query or "").strip()
    if _contains_any(normalized, SOURCE_TRIGGERS):
        return RagRoute(
            query_type="source_constrained",
            retrieval_strategy="hybrid_with_source_filter",
            body_fallback_slots=1,
            reason="matched source trigger",
        )
    if _contains_any(normalized, TIMELINE_RECENT_TRIGGERS):
        return RagRoute(
            query_type="timeline_or_recent",
            retrieval_strategy="time_aware_hybrid",
            body_fallback_slots=1,
            reason="matched timeline/recent trigger",
        )
    if _contains_any(normalized, CONTENT_DETAIL_TRIGGERS):
        return RagRoute(
            query_type="content_detail",
            retrieval_strategy="summary_with_body_fallback",
            body_fallback_slots=1,
            reason="matched content-detail trigger",
        )
    return RagRoute(
        query_type="title_or_entity",
        retrieval_strategy="summary_first",
        body_fallback_slots=0,
        reason="no detail/timeline/source trigger matched",
    )


def matched_source_terms(query: str) -> list[str]:
    return [trigger for trigger in SOURCE_TRIGGERS if trigger in (query or "")]


def is_econ_finance_query(query: str) -> bool:
    normalized = query or ""
    upper = normalized.upper()
    return any(trigger.upper() in upper for trigger in ECON_FINANCE_TRIGGERS)
