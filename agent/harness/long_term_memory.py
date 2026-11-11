"""Long-term (cross-session) user memory.

Modelled on the improvement library of Google's Harness2 (harness2/core/library.py, prompts.experience):

- Write gate. Nothing is stored unless the user explicitly states a durable preference ("以后回答都不超过
  80字") or an interest ("我主要关注童装产业"); everything else is NO_ENTRY. Matter facts are never durable
  memory -- they become wrong anchors later -- so news facts, remembered figures ("我记得苏超带动了500亿"),
  holdings and personal data are rejected outright. A preference may tighten the answer rules but never
  relax them: "以后都不用引用" is not stored, and a message that bargains over the rules ("你答应过",
  "我是管理员", "忽略规则") stores nothing at all, because a stored exemption outlives the session it was
  talked into.
- Evidence. Every entry keeps where it came from: session, turn and the user's own words.
- Budget. At most LONG_TERM_MEMORY_MAX_ENTRIES per user; adding one evicts the least recently used.
- Read side. A short always-on section plus preference defaults that rank below the session's and the
  current message's constraints. Memory is never evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.harness.context_manager import constraints_from_text

PREFERENCE_SCOPES = ("style", "detail_level", "max_chars", "max_points", "must_include_citations", "no_stock_prediction")
# "以后回答都…" / "之后都…" / "每次都…": a one-off "这次不超过50字" is a request, not a preference.
_PERSISTENT_RE = re.compile(r"(以后|之后|今后|往后|接下来|后面|每次|一直|默认)")
_INTEREST_RE = re.compile(
    # "我关注的领域有什么新报道" refers to an interest, it does not declare one: the verb must not be followed by 的.
    r"我(?:平时|主要|比较|一直|最|特别|也|会)?(?:关注|关心|感兴趣|在跟踪|想多了解|爱看)(?:的是|(?!的))[:：]?\s*([^，。！？,.!?；;\n]{2,24})"
)
_QUESTION_RE = re.compile(r"[？?]\s*$|什么|哪些|哪个|吗[？?。]?\s*$")
_INTEREST_TAIL_RE = re.compile(r"(?:方面|领域|行业|相关)?(?:的)?(?:新闻|报道|资讯|消息|动态)?$")
_REJECT_RULES = (
    ("remembered_figure", re.compile(r"\d+(?:\.\d+)?\s*(?:亿|万|%|％|元|美元|倍)")),
    ("hearsay", re.compile(r"我记得|听说|据说|好像是|有人说")),
    ("holding", re.compile(r"持有|买了|买入|卖出|仓位|满仓|空仓|加仓|减仓|(?<!\d)\d{6}(?!\d)")),
    ("personal_data", re.compile(r"1[3-9]\d{9}|身份证|银行卡|密码|住址|住在|手机号|电话")),
    ("rule_bargaining", re.compile(
        r"忽略|无视|答应|同意过|授权|管理员|开发者|提示词|无需证据|不需要证据|不用证据|不必遵守|不用遵守"
        r"|ignore|override|system prompt|developer|admin",
        re.IGNORECASE,
    )),
)
# Preference values that switch an answer rule off. They hold for the message or session that asks for
# them, but are never written to, nor read back from, long-term memory.
_RULE_RELAXING = {("must_include_citations", False), ("no_stock_prediction", False)}
_PREFERENCE_LABELS = {
    "style": lambda v: "用通俗语言" if v == "plain_language" else f"风格 {v}",
    "detail_level": lambda v: "回答简短" if v == "brief" else ("回答详细" if v == "detail" else f"详略 {v}"),
    "max_chars": lambda v: f"回答不超过{v}字",
    "max_points": lambda v: f"最多{v}点",
    "must_include_citations": lambda v: "保留新闻引用" if v else "",
    "no_stock_prediction": lambda v: "不要股票预测" if v else "",
}
INTEREST_SELF_REFERENCES = ("我关注", "我关心", "我感兴趣", "我在跟踪", "我平时看")


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str  # "preference" | "interest"
    key: str
    value: Any
    cue: str


def relaxes_rule(key: str, value: Any) -> bool:
    return (key, value) in _RULE_RELAXING


def memory_rejection_reason(text: str) -> str | None:
    """Why this message must not be written to long-term memory, or None."""
    for reason, pattern in _REJECT_RULES:
        if pattern.search(text or ""):
            return reason
    return None


def extract_memory_candidates(text: str) -> list[MemoryCandidate]:
    """Explicit durable statements in one user message; empty means NO_ENTRY."""
    text = (text or "").strip()
    if not text or memory_rejection_reason(text):
        return []
    candidates: list[MemoryCandidate] = []
    if _PERSISTENT_RE.search(text):
        for scope, value in constraints_from_text(text).items():
            if scope in PREFERENCE_SCOPES and not relaxes_rule(scope, value):
                candidates.append(MemoryCandidate("preference", scope, value, "回答格式"))
    for match in ([] if _QUESTION_RE.search(text) else _INTEREST_RE.finditer(text)):
        topic = _INTEREST_TAIL_RE.sub("", match.group(1).strip()).strip("的 ")
        if len(topic) >= 2:
            candidates.append(MemoryCandidate("interest", topic[:24], True, "用户提到“我关注的领域”或泛问新闻时"))
    return candidates


def _active_preferences(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Rows written before the write gate refused rule exemptions are still in the table; skip them here.
    return [
        entry for entry in entries
        if entry.get("kind") == "preference" and not relaxes_rule(entry["key"], entry.get("value"))
    ]


def preference_constraints(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {entry["key"]: entry.get("value") for entry in _active_preferences(entries)}


def interest_topics(entries: list[dict[str, Any]]) -> list[str]:
    return [str(entry["key"]) for entry in entries if entry.get("kind") == "interest"]


def interest_retrieval_hint(query: str, entries: list[dict[str, Any]]) -> str:
    """Interests only steer retrieval when the user points at them ("我关注的领域有什么新报道")."""
    if not any(marker in (query or "") for marker in INTEREST_SELF_REFERENCES):
        return ""
    return " ".join(interest_topics(entries)[:3])


def render_long_term_memory(entries: list[dict[str, Any]], max_chars: int = 300) -> str:
    """The always-on section; budgeted, and explicitly not evidence."""
    preferences = [
        label for entry in _active_preferences(entries)
        if (label := _PREFERENCE_LABELS.get(entry["key"], lambda v: "")(entry.get("value")))
    ]
    interests = interest_topics(entries)
    lines = []
    if preferences:
        lines.append("偏好：" + "；".join(preferences))
    if interests:
        lines.append("关注领域：" + "、".join(interests))
    if not lines:
        return ""
    body = "\n".join(lines)[:max_chars]
    return (
        '<long_term_memory use_as_evidence="false">\n'
        "跨会话记住的用户偏好和关注领域，只用于默认回答格式和理解“我关注的领域”；不是新闻事实。"
        "本轮或本会话里用户的新要求优先。\n"
        f"{body}\n</long_term_memory>"
    )
