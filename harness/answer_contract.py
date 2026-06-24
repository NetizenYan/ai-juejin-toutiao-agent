"""Answer contract construction and validation-mode resolution."""
from __future__ import annotations

from dataclasses import dataclass

from config.ai_conf import settings
from harness.query_understanding import UserQueryUnderstanding


@dataclass(frozen=True)
class AnswerContract:
    style: str = "plain_language"
    detail_level: str = "brief"
    max_points: int = 3
    max_chars: int | None = None
    must_include_citations: bool = True
    citation_style: str = "[news:ID]"
    evidence_only: bool = True
    requires_evidence: bool = True
    allow_background: bool = True
    background_policy: str = "one_sentence_plain_explanation"
    no_answer_policy: str = "refuse_with_suggestion"


def parse_enforce_routes(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def resolve_validation_mode(
    enabled: bool,
    validation_mode: str,
    enforce_routes: set[str],
    route: str | None,
) -> str:
    if not enabled:
        return "off"
    if route and route in enforce_routes:
        return "enforce"
    mode = (validation_mode or "shadow").strip().lower()
    if mode not in {"shadow", "enforce", "off"}:
        return "shadow"
    return mode


def build_answer_contract(
    understanding: UserQueryUnderstanding,
    intent: str,
    route: str | None = None,
) -> AnswerContract:
    is_news = intent in {"news_qa", "recommendation", "web_research"}
    requires_evidence = bool(is_news and settings.answer_contract_require_evidence_for_news)
    must_include_citations = bool(is_news and settings.answer_contract_require_citations_for_news)

    if understanding.must_include_citations is not None:
        must_include_citations = understanding.must_include_citations

    if intent == "general_chat":
        requires_evidence = False
        must_include_citations = False

    return AnswerContract(
        style=understanding.style or settings.answer_contract_default_style,
        detail_level=understanding.detail_level or settings.answer_contract_default_detail,
        max_points=understanding.max_points or settings.answer_contract_default_max_points,
        max_chars=understanding.max_chars,
        must_include_citations=must_include_citations,
        citation_style="[news:ID]",
        evidence_only=requires_evidence,
        requires_evidence=requires_evidence,
        allow_background=settings.answer_contract_allow_background,
        background_policy=settings.answer_contract_background_policy,
        no_answer_policy=settings.answer_no_evidence_policy,
    )
