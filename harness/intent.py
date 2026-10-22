"""Deterministic intent and fallback routing for the Agent harness."""

from __future__ import annotations

import re

from harness.rag_query_router import ECON_FINANCE_TRIGGERS

URL_RE = re.compile(r"https?://[^\s，。！？）)]+", re.IGNORECASE)
WEB_KEYWORDS = ("联网", "网页", "网上", "原文", "url", "链接", "http://", "https://")
NEWS_KEYWORDS = (
    "新闻",
    "资讯",
    "文章",
    "头条",
    "报道",
    "最近",
    "热点",
    "ai",
    "人工智能",
    "芯片",
    "金融",
    "财经",
    "宏观",
    "新质生产力",
    "高质量发展",
    "科技创新",
    "产业升级",
    "新能源",
    "制造业",
    "半导体",
    "政策",
    "利好",
    "人民日报",
    "经济日报",
    "新闻联播",
    "央视",
    "新华社",
)
# Public-affairs vocabulary: questions about policy, projects, infrastructure or livelihoods are news
# questions even without the words 新闻/报道. Classifying them as general_chat skips retrieval and lets
# the model answer ungrounded (e.g. "我国首个海上二氧化碳封存示范项目有什么新进展？").
PUBLIC_AFFAIRS_KEYWORDS = (
    "政策",
    "进展",
    "项目",
    "工程",
    "示范",
    "试点",
    "规划",
    "改革",
    "国务院",
    "发改委",
    "发布会",
    "能源",
    "电力",
    "交通",
    "基建",
    "运河",
    "港口",
    "铁路",
    "航运",
    "民生",
    "就业",
    "养老",
    "医保",
    "社保",
)
# Reuse the econ vocabulary the RAG router already routes on, so intent and collection routing agree.
NEWS_TOPIC_KEYWORDS = tuple(dict.fromkeys(PUBLIC_AFFAIRS_KEYWORDS + tuple(t.lower() for t in ECON_FINANCE_TRIGGERS)))
RECOMMEND_KEYWORDS = ("推荐", "看看", "相关文章", "相似")
INVESTMENT_BOUNDARY_KEYWORDS = (
    "股票",
    "a股",
    "个股",
    "板块",
    "买入",
    "卖出",
    "投资建议",
    "推荐我买",
    "一定利好",
    "必涨",
    "涨跌",
)
CONSTRAINT_ONLY_MARKERS = ("之后都", "后面都", "以后都", "接下来都")
CONSTRAINT_WORDS = ("简单", "简短", "不超过", "保留引用", "带引用", "新闻证据引用")
# "新闻 123" / "文章#88" / "id:5"; a number followed by 年/月/日/条... is a date or count, not an id.
NEWS_ID_RE = re.compile(
    r"(?:新闻|文章|(?<![a-z0-9])id)\s*[:：#]?\s*([0-9]{1,10})(?![0-9.%]|\s*[年月日号条篇个则项])",
    re.IGNORECASE,
)
# Must match RetrieveNewsArgs / NewsSearchArgs and WebSearchArgs max_length in tool_registry.
MAX_RETRIEVAL_QUERY_CHARS = 200
MAX_WEB_SEARCH_QUERY_CHARS = 240


def _has_keyword(text: str, keyword: str) -> bool:
    """ASCII keywords match whole words only, so "ai" does not hit "email"."""
    if keyword.isascii() and keyword.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(_has_keyword(text, keyword) for keyword in keywords)


def _clip_query(text: str, limit: int) -> str:
    """Keep head and tail of an over-long query instead of letting validation drop the call."""
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    head = limit // 2
    tail = limit - head - 1
    return f"{value[:head]} {value[-tail:]}"


def detect_intent(message: str) -> str:
    """Return the harness-owned intent label; models do not decide auth/routing."""
    normalized = (message or "").strip().lower()
    if not normalized:
        return "general_chat"
    if any(marker in normalized for marker in CONSTRAINT_ONLY_MARKERS) and any(
        word in normalized for word in CONSTRAINT_WORDS
    ):
        return "general_chat"
    if URL_RE.search(message or "") or _has_any_keyword(normalized, WEB_KEYWORDS):
        return "web_research"
    if _has_any_keyword(normalized, INVESTMENT_BOUNDARY_KEYWORDS):
        return "news_qa"
    if NEWS_ID_RE.search(normalized):
        return "news_lookup"
    if _has_any_keyword(normalized, RECOMMEND_KEYWORDS):
        return "recommendation"
    if _has_any_keyword(normalized, NEWS_KEYWORDS) or _has_any_keyword(normalized, NEWS_TOPIC_KEYWORDS):
        return "news_qa"
    return "general_chat"


def build_fallback_tool_calls(message: str, user_id: int | None = None) -> list[dict]:
    """Fallback when local models do not emit OpenAI tool calls reliably."""
    intent = detect_intent(message)
    if intent == "general_chat":
        return []
    if intent == "web_research":
        match = URL_RE.search(message or "")
        if match:
            return [{
                "name": "web_capture_ocr",
                "arguments": {"url": match.group(0)},
            }]
        return [{
            "name": "web_search",
            "arguments": {"query": _clip_query(message, MAX_WEB_SEARCH_QUERY_CHARS), "limit": 5},
        }]
    if intent == "news_lookup":
        detail_match = NEWS_ID_RE.search((message or "").lower())
        if detail_match and int(detail_match.group(1)) >= 1:
            return [{
                "name": "news_detail",
                "arguments": {"news_id": int(detail_match.group(1))},
            }]
        return []
    if intent == "recommendation":
        # 无主题的"推荐/看看"→ 返回热门/最新候选（与是否有浏览历史无关）
        return [{
            "name": "recommend_news",
            "arguments": {"limit": 5},
        }]

    # news_qa 默认走语义检索（RAG）
    return [{
        "name": "retrieve_news",
        "arguments": {"query": _clip_query(message, MAX_RETRIEVAL_QUERY_CHARS), "limit": 5},
    }]
