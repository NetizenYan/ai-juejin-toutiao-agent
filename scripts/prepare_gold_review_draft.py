"""Prepare a draft review-label file for retrieval-gold candidates.

The output is a review aid only. It must not be treated as formal reviewed
labels until a human reviewer accepts or edits each row.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


EVIDENCE_ID_RE = re.compile(r"news:[a-z]+:[0-9a-f]+")
REFUSAL_CASE_TYPES = {"G_no_answer", "H_investment_boundary"}
GROUNDED_INFERENCE_RE = re.compile(r"(帮助|启发|意义|关系|作用|影响)")
INVESTMENT_FORBIDDEN = ["推荐具体股票", "推荐买入卖出", "保证收益", "短线操作建议", "加仓建议"]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    jsonl_path = Path(path)
    if not jsonl_path.exists():
        return rows
    for line_no, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{jsonl_path}: line {line_no} must be a JSON object")
        rows.append(value)
    return rows


def _stable_gold_id(candidate_id: str) -> str:
    base = candidate_id.removeprefix("candidate_")
    return f"{base}_reviewed"


def _query_fields(query_or_turns: list[str]) -> dict[str, Any]:
    if len(query_or_turns) == 1:
        return {"question": query_or_turns[0], "turns": None}
    return {"question": None, "turns": query_or_turns}


def _extract_evidence_ids(reason: str) -> list[str]:
    seen: set[str] = set()
    evidence_ids: list[str] = []
    for evidence_id in EVIDENCE_ID_RE.findall(reason):
        if evidence_id not in seen:
            seen.add(evidence_id)
            evidence_ids.append(evidence_id)
    return evidence_ids


def _expected_route(case_type: str) -> str:
    if case_type == "G_no_answer":
        return "default"
    return "econ_finance_query"


def _is_grounded_inference_follow_up(case_type: str, query_or_turns: list[str]) -> bool:
    if case_type != "B_context_follow_up" or len(query_or_turns) < 2:
        return False
    return bool(GROUNDED_INFERENCE_RE.search(str(query_or_turns[-1])))


def _is_false_premise_follow_up(query_or_turns: list[str]) -> bool:
    if len(query_or_turns) < 2:
        return False
    tail = str(query_or_turns[-1])
    return any(marker in tail for marker in ("是不是", "已经", "说明", "确认"))


def _conditional_metadata(case_type: str, query_or_turns: list[str]) -> dict[str, Any]:
    if _is_grounded_inference_follow_up(case_type, query_or_turns):
        return {
            "answer_mode": "context_follow_up_explanation",
            "requires_grounded_inference": True,
        }
    if case_type == "G_no_answer":
        false_follow_up = _is_false_premise_follow_up(query_or_turns)
        return {
            "no_answer_mode": "false_premise_follow_up" if false_follow_up else "unsupported_claim",
            "should_refuse_false_claim": True,
            "allowed_fact_summary": bool(false_follow_up),
        }
    if case_type == "H_investment_boundary":
        return {
            "should_refuse_investment_advice": True,
            "allowed_fact_summary": True,
            "forbidden": INVESTMENT_FORBIDDEN,
        }
    return {}


def prepare_review_draft(
    candidates: list[dict[str, Any]],
    formal_gold: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_gold_ids = {str(row.get("id", "")) for row in formal_gold if row.get("id")}
    draft_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        candidate_id = str(candidate["id"])
        case_type = str(candidate["case_type"])
        reason = str(candidate.get("reason", ""))
        query_or_turns = list(candidate.get("query_or_turns") or [])
        mapped_gold_id = candidate_id.removeprefix("candidate_")

        if mapped_gold_id in existing_gold_ids:
            draft_rows.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "merge_with_existing",
                    "existing_gold_id": mapped_gold_id,
                    "case_type": case_type,
                    "notes": (
                        "Draft triage: candidate appears to duplicate an existing formal "
                        "gold id; review before counting it as new coverage."
                    ),
                }
            )
            continue

        evidence_ids = _extract_evidence_ids(reason)
        if case_type in REFUSAL_CASE_TYPES:
            draft_rows.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "accept_as_gold",
                    "gold_id": _stable_gold_id(candidate_id),
                    **_query_fields(query_or_turns),
                    "expected_route": _expected_route(case_type),
                    "gold_evidence_ids": [],
                    "should_answer": False,
                    "should_refuse": True,
                    "must_have_citations": False,
                    "case_type": case_type,
                    **_conditional_metadata(case_type, query_or_turns),
                    "notes": "Draft triage: refusal or no-answer boundary case; requires manual confirmation.",
                }
            )
        elif evidence_ids:
            draft_rows.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "accept_as_gold",
                    "gold_id": _stable_gold_id(candidate_id),
                    **_query_fields(query_or_turns),
                    "expected_route": _expected_route(case_type),
                    "gold_evidence_ids": evidence_ids,
                    "should_answer": True,
                    "should_refuse": False,
                    "must_have_citations": True,
                    "case_type": case_type,
                    **_conditional_metadata(case_type, query_or_turns),
                    "notes": "Draft triage: evidence ids were extracted from candidate reason; verify manually.",
                }
            )
        else:
            draft_rows.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "needs_evidence_lookup",
                    "case_type": case_type,
                    "notes": (
                        "Draft triage: no stable evidence ids were found in the candidate "
                        "reason; look up evidence before accepting as gold."
                    ),
                }
            )

    return draft_rows


def _render_summary(rows: list[dict[str, Any]]) -> str:
    decision_counts = Counter(str(row.get("decision")) for row in rows)
    case_counts = Counter(str(row.get("case_type")) for row in rows)
    lines = [
        "# Reviewed Labels Draft",
        "",
        "This is a draft review aid, not the formal reviewed-label file.",
        "",
        "## Summary",
        "",
        f"- Draft rows: {len(rows)}",
        f"- Suggested accepts: {decision_counts.get('accept_as_gold', 0)}",
        f"- Suggested merges: {decision_counts.get('merge_with_existing', 0)}",
        f"- Needs evidence lookup: {decision_counts.get('needs_evidence_lookup', 0)}",
        f"- Suggested rejects: {decision_counts.get('reject', 0)}",
        "",
        "## By Case Type",
        "",
        "| Case type | Draft rows |",
        "| --- | ---: |",
    ]
    for case_type in sorted(case_counts):
        lines.append(f"| `{case_type}` | {case_counts[case_type]} |")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not copy this draft wholesale into formal gold.",
            "- Review every `accept_as_gold` row before writing it to `reviewed_labels_20260622.jsonl`.",
            "- Treat `merge_with_existing` rows as non-new coverage unless a reviewer rewrites them.",
            "- Do not use this draft for tuning or held-out split creation.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_review_draft(
    candidates_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any]:
    rows = prepare_review_draft(load_jsonl(candidates_path), load_jsonl(gold_path))
    Path(output_path).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    Path(summary_path).write_text(_render_summary(rows), encoding="utf-8")
    decision_counts = Counter(str(row.get("decision")) for row in rows)
    return {
        "row_count": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "output_path": str(output_path),
        "summary_path": str(summary_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--output", default="eval/gold/reviewed_labels_draft_20260622.jsonl")
    parser.add_argument("--summary", default="eval/gold/REVIEWED_LABELS_DRAFT_20260622.md")
    args = parser.parse_args(argv)

    summary = write_review_draft(args.candidates, args.gold, args.output, args.summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
