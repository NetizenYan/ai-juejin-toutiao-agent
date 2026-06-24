"""Report projected gold coverage from reviewed-label decisions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_TARGET_TOTAL = 100
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


@dataclass
class ReviewedLabelCoverageSummary:
    formal_count: int
    label_count: int
    accepted_count: int
    merge_count: int
    needs_lookup_count: int
    rejected_count: int
    projected_formal_count: int
    target_total: int
    formal_counts: dict[str, int]
    accepted_counts: dict[str, int]
    merge_counts: dict[str, int]
    projected_counts_after_accepts: dict[str, int]
    deficits_after_accepts: dict[str, int]
    blockers: list[str]


def _case_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("case_type", "UNKNOWN")) for row in rows)


def summarize_reviewed_label_coverage(
    gold_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> ReviewedLabelCoverageSummary:
    coverage_targets = targets or DEFAULT_TARGETS
    accepted_rows = [row for row in label_rows if row.get("decision") == "accept_as_gold"]
    merge_rows = [row for row in label_rows if row.get("decision") == "merge_with_existing"]
    lookup_rows = [row for row in label_rows if row.get("decision") == "needs_evidence_lookup"]
    rejected_rows = [row for row in label_rows if row.get("decision") == "reject"]

    formal_counts = _case_counts(gold_rows)
    accepted_counts = _case_counts(accepted_rows)
    merge_counts = _case_counts(merge_rows)
    case_types = sorted(set(coverage_targets) | set(formal_counts) | set(accepted_counts) | set(merge_counts))
    projected = {
        case_type: formal_counts.get(case_type, 0) + accepted_counts.get(case_type, 0)
        for case_type in case_types
    }
    deficits = {
        case_type: max(0, coverage_targets.get(case_type, 0) - projected.get(case_type, 0))
        for case_type in case_types
    }

    projected_formal_count = len(gold_rows) + len(accepted_rows)
    blockers: list[str] = []
    if not accepted_rows:
        blockers.append("no accepted reviewed labels")
    if projected_formal_count < target_total:
        blockers.append(f"projected formal count {projected_formal_count} is below {target_total}")
    for case_type, deficit in deficits.items():
        if deficit:
            blockers.append(f"{case_type} remains below target by {deficit}")
    if lookup_rows:
        blockers.append(f"{len(lookup_rows)} reviewed labels still need evidence lookup")

    return ReviewedLabelCoverageSummary(
        formal_count=len(gold_rows),
        label_count=len(label_rows),
        accepted_count=len(accepted_rows),
        merge_count=len(merge_rows),
        needs_lookup_count=len(lookup_rows),
        rejected_count=len(rejected_rows),
        projected_formal_count=projected_formal_count,
        target_total=target_total,
        formal_counts={case_type: formal_counts.get(case_type, 0) for case_type in case_types},
        accepted_counts={case_type: accepted_counts.get(case_type, 0) for case_type in case_types},
        merge_counts={case_type: merge_counts.get(case_type, 0) for case_type in case_types},
        projected_counts_after_accepts=projected,
        deficits_after_accepts=deficits,
        blockers=blockers,
    )


def render_markdown(summary: ReviewedLabelCoverageSummary) -> str:
    lines = [
        "# Reviewed Label Coverage",
        "",
        "This report is read-only. It projects coverage if accepted reviewed-label rows are promoted.",
        "",
        "## Summary",
        "",
        f"- Formal gold count: {summary.formal_count}",
        f"- Reviewed-label rows: {summary.label_count}",
        f"- Accepted rows: {summary.accepted_count}",
        f"- Merge rows: {summary.merge_count}",
        f"- Needs evidence lookup: {summary.needs_lookup_count}",
        f"- Rejected rows: {summary.rejected_count}",
        f"- Projected formal count after accepts: {summary.projected_formal_count}",
        f"- Target total: {summary.target_total}",
        "",
        "## Class Projection",
        "",
        "| Case type | Formal | Accepted | Merged | Projected formal | Remaining deficit |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case_type in summary.formal_counts:
        lines.append(
            "| "
            f"`{case_type}` | "
            f"{summary.formal_counts[case_type]} | "
            f"{summary.accepted_counts[case_type]} | "
            f"{summary.merge_counts[case_type]} | "
            f"{summary.projected_counts_after_accepts[case_type]} | "
            f"{summary.deficits_after_accepts[case_type]} |"
        )

    lines.extend(["", "## Blockers", ""])
    if summary.blockers:
        for blocker in summary.blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- None for reviewed-label coverage. Formal promotion, split creation, and baselines are still separate gates.")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report does not modify formal gold.",
            "- Merge rows do not count as new coverage.",
            "- Do not use draft labels as held-out cases before manual confirmation.",
            "- Do not run automatic tuning until the tuning gate checker returns `ok=true`.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_reviewed_label_coverage_report(
    gold_path: str | Path,
    labels_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> ReviewedLabelCoverageSummary:
    summary = summarize_reviewed_label_coverage(
        load_jsonl(gold_path),
        load_jsonl(labels_path),
        targets=targets,
        target_total=target_total,
    )
    Path(report_path).write_text(render_markdown(summary), encoding="utf-8")
    Path(json_report_path).write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--labels", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_COVERAGE_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_COVERAGE_20260622.json")
    args = parser.parse_args(argv)

    summary = write_reviewed_label_coverage_report(args.gold, args.labels, args.report, args.json_report)
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0 if not summary.blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
