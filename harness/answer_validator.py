"""Answer Contract v1 validator.

The validator catches citation and hard-constraint failures. It does not prove
answers are fully hallucination-free; it only labels obvious risk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import floor
from typing import Any

from harness.answer_contract import AnswerContract

CITATION_RE = re.compile(r"\[news:[A-Za-z0-9:_\-]+\]")
NON_EVIDENCE_PHRASES = (
    "根据我的知识",
    "据我了解",
    "我认为",
    "网上资料",
    "从常识看",
)
REFUSAL_PATTERNS = (
    "未找到可靠新闻证据",
    "没有找到可靠新闻证据",
    "站内未找到",
    "暂无可靠新闻证据",
    "没有检索到可靠",
    "没有找到足够匹配",
    "换个关键词",
)
INVESTMENT_CERTAINTY_QUERY_TERMS = (
    "一定利好",
    "必然利好",
    "肯定利好",
    "必涨",
    "稳赚",
    "买入",
    "卖出",
    "投资建议",
)
INVESTMENT_UNSAFE_ANSWER_TERMS = (
    "一定利好",
    "必然利好",
    "肯定利好",
    "必涨",
    "稳赚",
    "可以买入",
    "建议买入",
    "建议卖出",
)
INVESTMENT_GUARD_TERMS = (
    "不能判断一定利好",
    "不一定",
    "可能",
    "倾向于",
    "仍需结合",
    "证据不足",
    "不构成投资建议",
    "不能预测",
    "不能判断",
    "无法判断",
    "不能保证",
    "无法保证",
    "不能推荐",
    "无法推荐",
    "无法直接推荐",
)
# Certainty / advice questions the fixed term list missed, e.g. "是不是必然带动半导体股票上涨",
# "能不能直接推荐几只最值得买的股票", "能保证科技基金收益上涨", "应该加仓哪些行业基金".
INVESTMENT_CERTAINTY_QUERY_RE = re.compile(
    r"(一定|必然|肯定|必定|保证|稳)[^，。？?！!]{0,10}(上涨|涨|利好|收益|赚)"
    r"|推荐[^，。？?！!]{0,6}(买|股票|基金|个股)"
    r"|最值得买|(买|加仓|减仓|配置)哪|应该(买|加仓|减仓)|抄底"
)
UNQUOTED_NAMED_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,}(?:计划|工程|方案|行动|法案)[0-9A-Za-z]{2,}")


@dataclass
class AnswerValidationResult:
    passed: bool
    hallucination_risk: str = "low"
    constraint_violations: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    unsupported_warnings: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)

    def to_metadata(self, mode: str, rewrite_count: int) -> dict[str, Any]:
        return {
            "mode": mode,
            "passed": self.passed,
            "wouldRewrite": mode == "shadow" and not self.passed,
            "rewriteCount": rewrite_count,
            "constraint_violations": list(self.constraint_violations),
            "invalid_refs": list(self.invalid_refs),
            "hallucination_risk": self.hallucination_risk,
            "risk_reasons": list(self.risk_reasons),
            "unsupported_warnings": list(self.unsupported_warnings),
        }

    def to_done_summary(self, mode: str, rewrite_count: int) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "rewriteCount": rewrite_count,
            "mode": mode,
            "hallucinationRisk": self.hallucination_risk,
        }


def extract_citations(answer: str) -> list[str]:
    return [match[1:-1] for match in CITATION_RE.findall(answer or "")]


# A refusal is a citation-free "nothing found" reply. Answers that carry claims besides a
# refusal phrase must still pass the normal checks, so only a short remainder is allowed.
REFUSAL_MAX_OTHER_CHARS = 40
# Split down to clauses: a hallucinated sentence can end with ", 站内未找到更多报道".
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;，,\n]+")


def _is_refusal_sentence(sentence: str) -> bool:
    if any(token in sentence for token in REFUSAL_PATTERNS):
        return True
    return "未找到" in sentence and any(token in sentence for token in ("可靠", "证据", "新闻", "报道", "相关内容"))


def is_refusal(answer: str) -> bool:
    compact = re.sub(r"[\s*_`]+", "", answer or "")
    if not compact or CITATION_RE.search(compact):
        return False
    sentences = [part for part in _SENTENCE_SPLIT_RE.split(compact) if part]
    refusal_sentences = [part for part in sentences if _is_refusal_sentence(part)]
    if not refusal_sentences:
        return False
    other_chars = sum(len(part) for part in sentences if not _is_refusal_sentence(part))
    return other_chars <= REFUSAL_MAX_OTHER_CHARS


_is_refusal = is_refusal


def _evidence_ref(item: Any) -> str | None:
    if isinstance(item, str):
        return item if item.startswith("news:") else None
    if not isinstance(item, dict):
        return None
    ref = item.get("ref") or item.get("evidence_id")
    if isinstance(ref, str) and ref.startswith("news:"):
        return ref
    item_id = item.get("id") or item.get("news_id")
    if item_id is not None:
        return f"news:{item_id}"
    return None


def _evidence_texts(evidence_pack: list[Any]) -> list[str]:
    texts: list[str] = []
    for item in evidence_pack:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        parts = [
            item.get("title"),
            item.get("summary"),
            item.get("snippet"),
            item.get("content_excerpt"),
            item.get("chunk_text"),
        ]
        for part in parts:
            if part:
                texts.append(str(part))
    return texts


def _has_large_copy(answer: str, evidence_texts: list[str], threshold: int = 50) -> bool:
    compact_answer = re.sub(r"\s+", "", answer or "")
    for text in evidence_texts:
        compact_text = re.sub(r"\s+", "", text or "")
        if not compact_text:
            continue
        if len(compact_text) >= threshold:
            for start in range(0, len(compact_text) - threshold + 1):
                if compact_text[start:start + threshold] in compact_answer:
                    return True
        if len(compact_text) >= 10:
            copied_total = compact_answer.count(compact_text) * len(compact_text)
            if copied_total >= threshold:
                return True
    return False


def _add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _unsupported_query_terms(query: str, evidence_text: str) -> list[str]:
    terms = re.findall(r"[“\"]([^”\"]{2,40})[”\"]", query or "")
    terms.extend(UNQUOTED_NAMED_TERM_RE.findall(query or ""))
    unsupported: list[str] = []
    for term in terms:
        if term and term not in evidence_text and term not in unsupported:
            unsupported.append(term)
    return unsupported


# Questions about markets at all (not only certainty ones): these get the conservative-wording
# instruction and disclaimer; other questions are told to leave markets out.
INVESTMENT_TOPIC_TERMS = (
    "股票", "股市", "a股", "个股", "板块", "基金", "涨跌", "上涨", "下跌", "行情",
    "买入", "卖出", "加仓", "减仓", "抄底", "投资建议", "收益", "利好", "利空",
)


def asks_about_investment(query: str | None) -> bool:
    text = (query or "").lower()
    return asks_investment_certainty(query) or any(term in text for term in INVESTMENT_TOPIC_TERMS)


def asks_investment_certainty(query: str | None) -> bool:
    if not query:
        return False
    return any(term in query for term in INVESTMENT_CERTAINTY_QUERY_TERMS) or bool(INVESTMENT_CERTAINTY_QUERY_RE.search(query))


_asks_investment_certainty = asks_investment_certainty


def validate_answer(
    answer: str,
    contract: AnswerContract,
    evidence_pack: list[Any],
    query: str | None = None,
) -> AnswerValidationResult:
    answer = answer or ""
    violations: list[str] = []
    warnings: list[str] = []
    risk_reasons: list[str] = []
    invalid_refs: list[str] = []
    evidence_refs = {ref for ref in (_evidence_ref(item) for item in evidence_pack) if ref}
    has_evidence = bool(evidence_refs or evidence_pack)
    is_refusal = _is_refusal(answer)

    if contract.requires_evidence and not has_evidence:
        if is_refusal:
            return AnswerValidationResult(passed=True, hallucination_risk="low")
        _add_unique(violations, "no_evidence_fact_answer")

    citations = extract_citations(answer)
    for citation in citations:
        if citation not in evidence_refs:
            invalid_refs.append(citation)
    if invalid_refs:
        _add_unique(violations, "invalid_citation")

    if contract.must_include_citations and has_evidence and not citations and not is_refusal:
        _add_unique(violations, "missing_citation")

    if contract.max_chars is not None:
        max_allowed = floor(contract.max_chars * 1.05)
        if len(answer) > max_allowed:
            _add_unique(violations, "max_chars_exceeded")

    if any(phrase in answer for phrase in NON_EVIDENCE_PHRASES):
        _add_unique(violations, "non_evidence_expression")

    evidence_texts = _evidence_texts(evidence_pack)
    if query and not is_refusal:
        evidence_all_for_terms = "\n".join(evidence_texts)
        if _unsupported_query_terms(query, evidence_all_for_terms):
            _add_unique(violations, "evidence_not_support_query")
        has_guard = any(term in answer for term in INVESTMENT_GUARD_TERMS)
        if _asks_investment_certainty(query):
            if any(term in answer for term in INVESTMENT_UNSAFE_ANSWER_TERMS) and not has_guard:
                _add_unique(violations, "investment_advice_or_certainty")
            elif not has_guard:
                _add_unique(violations, "missing_investment_guard")
    # Certainty / advice wording is blocked in every answer, whatever was asked.
    if not is_refusal and any(term in answer for term in INVESTMENT_UNSAFE_ANSWER_TERMS) and not any(
        term in answer for term in INVESTMENT_GUARD_TERMS
    ):
        _add_unique(violations, "investment_advice_or_certainty")

    if evidence_texts and _has_large_copy(answer, evidence_texts):
        _add_unique(violations, "large_evidence_copy")

    evidence_all = "\n".join(evidence_texts)
    answer_without_citations = CITATION_RE.sub("", answer)
    answer_numbers = set(re.findall(r"\d{2,4}(?:\.\d+)?%?", answer_without_citations))
    evidence_numbers = set(re.findall(r"\d{2,4}(?:\.\d+)?%?", evidence_all))
    unsupported_numbers = answer_numbers - evidence_numbers
    if unsupported_numbers:
        _add_unique(warnings, "possible_unsupported_number_or_date")
        _add_unique(risk_reasons, "possible_unsupported_number_or_date")

    passed = not violations
    if violations:
        hallucination_risk = "high"
        risk_reasons.extend(v for v in violations if v not in risk_reasons)
    elif warnings:
        hallucination_risk = "medium"
    else:
        hallucination_risk = "low"

    return AnswerValidationResult(
        passed=passed,
        hallucination_risk=hallucination_risk,
        constraint_violations=violations,
        invalid_refs=invalid_refs,
        unsupported_warnings=warnings,
        risk_reasons=risk_reasons,
    )
