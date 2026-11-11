"""Deterministic intent and fallback routing for the Agent harness."""

from __future__ import annotations

import re

from harness.rag_query_router import ECON_FINANCE_TRIGGERS

URL_RE = re.compile(r"https?://[^\s，。！？）)]+", re.IGNORECASE)
WEB_KEYWORDS = ("联网", "网页", "网上", "原文", "url", "链接", "http://", "https://")
# "工业互联网" / "卫星物联网" / "车联网" contain "联网" but ask nothing of the web: they were routed to web search
# and, with it off, refused (EXT5: three 经济日报 questions, every time).
_NOT_WEB_TERMS_RE = re.compile(r"[互物车]联网")
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


# general_chat is recognised positively. Defaulting every question without a news keyword to
# general_chat skipped retrieval for plain factual questions ("在莫斯科参加HSK考试的人有多少？",
# "人形机器人运动会跳高金牌跳了多高？"): on a fresh test set 8 of 34 cases never searched.
SMALL_TALK_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|hi|hello|早上好|下午好|晚上好|晚安|谢谢|多谢|感谢|再见|拜拜)"
    r"|你是谁|介绍(?:一下)?你自己|你(?:能|会)(?:做|干)什么|你叫什么|你是什么模型"
    r"|笑话|讲个故事|写(?:一?句|一?首|一?段)|鼓励|安慰|随便聊|聊聊天|天气不错"
    r"|怎么翻译|翻译(?:一下|成)|怎么读|什么意思|^什么是\s*[a-z]"
    # Arithmetic only when the sum is what is asked: "“3+3”模式高考", "1-9月", "2014-01-22" and "5/10" inside a
    # news question skipped retrieval (EXT6 atk_cx6_027/057/087/117/147#2, five runs of one question).
    r"|(?:计算|算一下|算算)[^。？?\n]{0,6}\d+\s*(?:加|减|乘以?|除以?|[+\-*/×÷])\s*\d+"
    r"|\d+\s*(?:加|减|乘以?|除以?|[+\-*/×÷])\s*\d+\s*(?:等于|是多少|得多少|得几|是几|=|[？?。]?\s*$)",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(r"[？?]|多少|几(?:个|家|位|次|年|月|天|名|项|件)|什么|哪|谁|怎么|怎样|如何|为什么|为何|是否|有没有|吗[。！]?$")


def detect_intent(message: str) -> str:
    """Return the harness-owned intent label; models do not decide auth/routing."""
    normalized = (message or "").strip().lower()
    if not normalized:
        return "general_chat"
    if any(marker in normalized for marker in CONSTRAINT_ONLY_MARKERS) and any(
        word in normalized for word in CONSTRAINT_WORDS
    ):
        return "general_chat"
    if URL_RE.search(message or "") or _has_any_keyword(_NOT_WEB_TERMS_RE.sub("", normalized), WEB_KEYWORDS):
        return "web_research"
    if _has_any_keyword(normalized, INVESTMENT_BOUNDARY_KEYWORDS):
        return "news_qa"
    if NEWS_ID_RE.search(normalized):
        return "news_lookup"
    if _has_any_keyword(normalized, RECOMMEND_KEYWORDS):
        return "recommendation"
    if _has_any_keyword(normalized, NEWS_KEYWORDS) or _has_any_keyword(normalized, NEWS_TOPIC_KEYWORDS):
        return "news_qa"
    if SMALL_TALK_RE.search(normalized):
        return "general_chat"
    # A factual question in a news app is a news question; retrieval + validation refuse when the
    # station has nothing on it, so routing an off-topic question here costs a refusal, not a hallucination.
    if QUESTION_RE.search(normalized):
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
