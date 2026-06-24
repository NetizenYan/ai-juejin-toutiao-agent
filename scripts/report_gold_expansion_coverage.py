"""Report 3.3 retrieval gold expansion coverage."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_TARGET_TOTAL = 100
DEFAULT_MAX_TOTAL = 150
DEFAULT_TARGETS = {
    "A_exact_news_qa": 20,
    "B_context_follow_up": 20,
    "C_time_sensitive": 15,
    "D_source_limited": 15,
    "E_multi_document": 15,
    "F_similar_distractor": 10,
    "G_no_answer": 10,
    "H_investment_boundary": 10,
}


@dataclass
class CoverageSummary:
    formal_count: int
    candidate_count: int
    target_total: int
    max_total: int
    formal_counts: dict[str, int]
    candidate_counts: dict[str, int]
    projected_counts_if_all_candidates_accepted: dict[str, int]
    deficits_formal_only: dict[str, int]
    deficits_if_all_candidates_accepted: dict[str, int]
    total_deficit_formal_only: int
    total_deficit_if_all_candidates_accepted: int
    candidate_gaps: list[str]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    jsonl_path = Path(path)
    if not jsonl_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{jsonl_path}: line {line_no} must be a JSON object")
        rows.append(value)
    return rows


def _case_type_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("case_type", "UNKNOWN")) for row in rows)


def summarize_coverage(
    gold_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
    max_total: int = DEFAULT_MAX_TOTAL,
) -> CoverageSummary:
    coverage_targets = targets or DEFAULT_TARGETS
    formal_counts = _case_type_counts(gold_rows)
    candidate_counts = _case_type_counts(candidate_rows)
    case_types = sorted(set(coverage_targets) | set(formal_counts) | set(candidate_counts))

    projected = {
        case_type: formal_counts.get(case_type, 0) + candidate_counts.get(case_type, 0)
        for case_type in case_types
    }
    deficits_formal_only = {
        case_type: max(0, coverage_targets.get(case_type, 0) - formal_counts.get(case_type, 0))
        for case_type in case_types
    }
    deficits_if_all_candidates_accepted = {
        case_type: max(0, coverage_targets.get(case_type, 0) - projected.get(case_type, 0))
        for case_type in case_types
    }
    candidate_gaps = [
        case_type
        for case_type in case_types
        if candidate_counts.get(case_type, 0) == 0 and deficits_formal_only.get(case_type, 0) > 0
    ]

    formal_count = len(gold_rows)
    candidate_count = len(candidate_rows)
    return CoverageSummary(
        formal_count=formal_count,
        candidate_count=candidate_count,
        target_total=target_total,
        max_total=max_total,
        formal_counts={case_type: formal_counts.get(case_type, 0) for case_type in case_types},
        candidate_counts={case_type: candidate_counts.get(case_type, 0) for case_type in case_types},
        projected_counts_if_all_candidates_accepted=projected,
        deficits_formal_only=deficits_formal_only,
        deficits_if_all_candidates_accepted=deficits_if_all_candidates_accepted,
        total_deficit_formal_only=max(0, target_total - formal_count),
        total_deficit_if_all_candidates_accepted=max(0, target_total - formal_count - candidate_count),
        candidate_gaps=candidate_gaps,
    )


def render_markdown(summary: CoverageSummary) -> str:
    lines = [
        "# 3.3 Gold Expansion Coverage",
        "",
        "## Summary",
        "",
        f"- Formal gold count: {summary.formal_count}",
        f"- Candidate count: {summary.candidate_count}",
        f"- Target total: {summary.target_total}-{summary.max_total}",
        f"- Need {summary.total_deficit_formal_only} more formal cases to reach {summary.target_total} total.",
        (
            "- Need "
            f"{summary.total_deficit_if_all_candidates_accepted} more reviewed/accepted cases "
            f"to reach {summary.target_total} total."
        ),
        "",
        "## Class Coverage",
        "",
        "| Case type | Formal | Candidates | Projected if all accepted | Formal deficit | Projected deficit |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case_type in summary.formal_counts:
        lines.append(
            "| "
            f"`{case_type}` | "
            f"{summary.formal_counts[case_type]} | "
            f"{summary.candidate_counts[case_type]} | "
            f"{summary.projected_counts_if_all_candidates_accepted[case_type]} | "
            f"{summary.deficits_formal_only[case_type]} | "
            f"{summary.deficits_if_all_candidates_accepted[case_type]} |"
        )

    lines.extend(["", "## Candidate Gaps", ""])
    if summary.candidate_gaps:
        for case_type in summary.candidate_gaps:
            lines.append(f"- `{case_type}` has no current candidates and still has a coverage deficit.")
    else:
        lines.append("- No case type has both zero candidates and a remaining formal coverage deficit.")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is read-only.",
            "- Do not tune weights from this candidate set.",
            "- Do not promote candidates into formal gold before reviewed-label validation.",
            "- Do not create `scripts/tune_rag_weights.py` before the documented gate is met.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--report", default="eval/gold/GOLD_EXPANSION_COVERAGE_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json")
    args = parser.parse_args(argv)

    summary = summarize_coverage(load_jsonl(args.gold), load_jsonl(args.candidates))
    Path(args.report).write_text(render_markdown(summary), encoding="utf-8")
    Path(args.json_report).write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
