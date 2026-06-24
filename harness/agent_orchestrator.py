"""Deterministic role planning for the single-agent harness.

The current runtime is still a single agent. This module makes the internal
roles explicit so later multi-agent or delegated implementations can replace
one role at a time without changing the user-facing contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.anchor_resolver import looks_like_anchor_query


ANCHOR_INTERRUPT_STATES = {
    "WAITING_USER_CONFIRMATION",
    "NEEDS_EXTERNAL_RESEARCH",
    "INSUFFICIENT_EVIDENCE",
}


@dataclass(frozen=True)
class AgentRoleStep:
    role: str
    action: str
    status: str = "ready"
    details: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "action": self.action,
            "status": self.status,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class AgentOrchestrationPlan:
    roles: list[AgentRoleStep]
    next_action: str
    interrupt_user: bool = False

    def to_metadata(self) -> dict[str, Any]:
        return {
            "next_action": self.next_action,
            "interrupt_user": self.interrupt_user,
            "roles": [role.to_metadata() for role in self.roles],
        }


def _anchor_counts(anchor_resolution: Any) -> dict[str, Any]:
    candidates = list(getattr(anchor_resolution, "candidates", []) or [])
    leads = list(getattr(anchor_resolution, "leads", []) or [])
    return {
        "state": str(getattr(anchor_resolution, "state", "") or ""),
        "requires_user_confirmation": bool(getattr(anchor_resolution, "requires_user_confirmation", False)),
        "candidate_count": len(candidates),
        "lead_count": len(leads),
    }


def _external_verification_summary(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    external_candidate_count = 0
    for result in tool_results or []:
        holders: list[Any] = [result]
        item = result.get("item")
        if isinstance(item, dict):
            holders.append(item)
        holders.extend(entry for entry in (result.get("items") or []) if isinstance(entry, dict))
        tool_name = str(result.get("tool") or "")
        if tool_name in {"web_capture_ocr", "web_search", "web_fetch"}:
            external_candidate_count += 1
        for holder in holders:
            verification = holder.get("external_verification") if isinstance(holder, dict) else None
            if not isinstance(verification, dict):
                continue
            status = str(verification.get("verification_status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "external_candidate_count": external_candidate_count,
        "station_matched_count": status_counts.get("station_matched", 0),
        "unverified_count": status_counts.get("unverified", 0),
        "low_signal_count": status_counts.get("low_signal", 0),
        "conflict_count": status_counts.get("conflict", 0),
        "statuses": status_counts,
    }


def _next_action(anchor_resolution: Any, tool_results: list[dict[str, Any]], allowed_tools: set[str]) -> tuple[str, bool]:
    anchor_state = str(getattr(anchor_resolution, "state", "") or "")
    if anchor_state == "WAITING_USER_CONFIRMATION":
        return "ask_user_to_confirm_anchor", True
    if anchor_state == "NEEDS_EXTERNAL_RESEARCH":
        return "ask_for_external_research_or_more_clues", True
    if anchor_state == "INSUFFICIENT_EVIDENCE":
        return "ask_user_for_more_anchor_clues", True
    if allowed_tools and not tool_results:
        return "run_tool_layer", False
    if anchor_state == "ANCHOR_CONFIRMED":
        return "generate_answer_with_confirmed_anchor", False
    return "generate_answer", False


def build_agent_orchestration_plan(
    *,
    latest_user: str,
    retrieval_user: str,
    intent: str,
    allowed_tools: set[str],
    tool_results: list[dict[str, Any]],
    anchor_resolution: Any = None,
    confirmed_anchor: dict[str, Any] | None = None,
    session_context: Any = None,
    carryover_evidence_ids: list[str] | None = None,
) -> AgentOrchestrationPlan:
    anchor_details = _anchor_counts(anchor_resolution)
    evidence_details = _external_verification_summary(tool_results)
    next_action, interrupt_user = _next_action(anchor_resolution, tool_results, set(allowed_tools or set()))
    confirmed_anchor_id = ""
    if isinstance(confirmed_anchor, dict):
        confirmed_anchor_id = str(confirmed_anchor.get("anchor_id") or "")

    roles = [
        AgentRoleStep(
            role="QueryUnderstanding",
            action="classify_intent_and_anchor_need",
            details={
                "intent": str(intent or ""),
                "allowed_tools": sorted(str(tool) for tool in (allowed_tools or set())),
                "anchor_query": bool(anchor_resolution is not None or looks_like_anchor_query(latest_user)),
                "retrieval_query_changed": bool((retrieval_user or "") != (latest_user or "")),
            },
        ),
        AgentRoleStep(
            role="MemoryLedger",
            action="carry_confirmed_anchor_and_context_refs",
            details={
                "confirmed_anchor_id": confirmed_anchor_id,
                "carryover_evidence_ids": list(carryover_evidence_ids or []),
                "anchor_ledger_count": len(getattr(session_context, "anchor_ledger", []) or []),
                "topic_ledger_count": len(getattr(session_context, "topic_ledger", []) or []),
                "memory_is_evidence": bool(getattr(session_context, "memory_is_evidence", False)),
            },
        ),
        AgentRoleStep(
            role="AnchorResolver",
            action="resolve_or_confirm_news_anchor",
            details=anchor_details,
        ),
        AgentRoleStep(
            role="EvidenceVerifier",
            action="cross_check_external_evidence",
            details=evidence_details,
        ),
        AgentRoleStep(
            role="AnswerPlanner",
            action=next_action,
            details={
                "interrupt_user": interrupt_user,
                "tool_result_count": len(tool_results or []),
            },
        ),
    ]
    return AgentOrchestrationPlan(roles=roles, next_action=next_action, interrupt_user=interrupt_user)


__all__ = [
    "AgentOrchestrationPlan",
    "AgentRoleStep",
    "build_agent_orchestration_plan",
]
