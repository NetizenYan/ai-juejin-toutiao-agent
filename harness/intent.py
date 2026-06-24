"""Deterministic intent and fallback routing for the Agent harness."""

from __future__ import annotations

import re

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


def detect_intent(message: str) -> str:
    """Return the harness-owned intent label; models do not decide auth/routing."""
    normalized = (message or "").strip().lower()
    if not normalized:
        return "general_chat"
    if any(marker in normalized for marker in CONSTRAINT_ONLY_MARKERS) and any(
        word in normalized for word in CONSTRAINT_WORDS
    ):
        return "general_chat"
    if URL_RE.search(message or "") or any(keyword in normalized for keyword in WEB_KEYWORDS):
        return "web_research"
    if any(keyword in normalized for keyword in INVESTMENT_BOUNDARY_KEYWORDS):
        return "news_qa"
    if any(keyword in normalized for keyword in RECOMMEND_KEYWORDS):
        return "recommendation"
    if any(keyword in normalized for keyword in NEWS_KEYWORDS):
        return "news_qa"
    return "general_chat"


def build_fallback_tool_calls(message: str, user_id: int | None = None) -> list[dict]:
    """Fallback when local models do not emit OpenAI tool calls reliably."""
    intent = detect_intent(message)
    normalized = (message or "").strip().lower()
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
            "arguments": {"query": (message or "").strip(), "limit": 5},
        }]
    if intent == "recommendation":
        # 无主题的"推荐/看看"→ 返回热门/最新候选（与是否有浏览历史无关）
        return [{
            "name": "recommend_news",
            "arguments": {"limit": 5},
        }]

    detail_match = re.search(r"(?:新闻|文章|id)[:：#\s]*([0-9]{1,10})", message or "", re.IGNORECASE)
    if detail_match:
        return [{
            "name": "news_detail",
            "arguments": {"news_id": int(detail_match.group(1))},
        }]

    # news_qa 默认走语义检索（RAG）
    return [{
        "name": "retrieve_news",
        "arguments": {"query": (message or "").strip(), "limit": 5},
    }]
