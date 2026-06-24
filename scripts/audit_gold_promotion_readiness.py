"""Audit whether reviewed retrieval labels are ready for formal gold promotion.

This report is read-only. It compares the official reviewed-label file with the
draft labels and explains why formal promotion is or is not currently allowed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.report_reviewed_label_coverage import (
    DEFAULT_TARGETS,
    DEFAULT_TARGET_TOTAL,
    summarize_reviewed_label_coverage,
)


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


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _label_counts(label_rows: list[dict[str, Any]]) -> dict[str, int]:
    decisions = {
        "accept_as_gold": 0,
        "merge_with_existing": 0,
        "needs_evidence_lookup": 0,
        "reject": 0,
    }
    for row in label_rows:
        decision = str(row.get("decision", ""))
        if decision in decisions:
            decisions[decision] += 1
    return decisions


def validate_reviewed_labels_from_rows(
    candidate_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {str(row.get("id", "")) for row in candidate_rows if row.get("id")}
    seen_candidate_ids: set[str] = set()
    seen_gold_ids: set[str] = set()
    errors: list[str] = []
    accepted_count = 0
    rejected_count = 0

    for idx, row in enumerate(label_rows, start=1):
        candidate_id = str(row.get("candidate_id", ""))
        decision = row.get("decision")
        if not candidate_id:
            errors.append(f"line {idx}: candidate_id is required")
        elif candidate_id not in candidate_ids:
            errors.append(f"line {idx}: unknown candidate_id {candidate_id}")
        elif candidate_id in seen_candidate_ids:
            errors.append(f"line {idx}: duplicate candidate_id {candidate_id}")
        seen_candidate_ids.add(candidate_id)

        if decision not in {"accept_as_gold", "merge_with_existing", "needs_evidence_lookup", "reject"}:
            errors.append(f"line {idx}: invalid decision {decision!r}")
            continue

        if decision == "accept_as_gold":
            accepted_count += 1
            gold_id = str(row.get("gold_id", ""))
            if not gold_id:
                errors.append(f"line {idx}: accept_as_gold requires gold_id")
            elif gold_id in seen_gold_ids:
                errors.append(f"line {idx}: duplicate gold_id {gold_id}")
            seen_gold_ids.add(gold_id)
            if not row.get("question") and not row.get("turns"):
                errors.append(f"line {idx}: accept_as_gold requires question or turns")
            evidence_ids = row.get("gold_evidence_ids")
            if not isinstance(evidence_ids, list):
                errors.append(f"line {idx}: accept_as_gold requires gold_evidence_ids to be a list")
            elif row.get("should_answer") and row.get("must_have_citations") and not evidence_ids:
                errors.append(f"line {idx}: answerable accept_as_gold requires non-empty gold_evidence_ids")
            for field in (
                "expected_route",
                "should_answer",
                "should_refuse",
                "must_have_citations",
                "case_type",
                "notes",
            ):
                if field not in row:
                    errors.append(f"line {idx}: accept_as_gold requires {field}")
        elif decision == "reject":
            rejected_count += 1
            if not row.get("notes"):
                errors.append(f"line {idx}: reject requires notes")
        elif not row.get("notes"):
            errors.append(f"line {idx}: {decision} requires notes")

    return {
        "ok": not errors,
        "row_count": len(label_rows),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "errors": errors,
    }


def _coverage_summary(
    gold_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    *,
    targets: dict[str, int],
    target_total: int,
) -> dict[str, Any]:
    return asdict(
        summarize_reviewed_label_coverage(
            gold_rows,
            label_rows,
            targets=targets,
            target_total=target_total,
        )
    )


def audit_promotion_readiness(
    gold_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    official_label_rows: list[dict[str, Any]],
    draft_label_rows: list[dict[str, Any]],
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> dict[str, Any]:
    coverage_targets = targets or DEFAULT_TARGETS
    official_validation = validate_reviewed_labels_from_rows(candidate_rows, official_label_rows)
    draft_validation = validate_reviewed_labels_from_rows(candidate_rows, draft_label_rows)
    official_coverage = _coverage_summary(
        gold_rows,
        official_label_rows,
        targets=coverage_targets,
        target_total=target_total,
    )
    draft_coverage = _coverage_summary(
        gold_rows,
        draft_label_rows,
        targets=coverage_targets,
        target_total=target_total,
    )

    blockers: list[str] = []
    warnings: list[str] = []

    if not official_label_rows:
        blockers.append("official reviewed labels are empty")
    if not official_validation["ok"]:
        blockers.extend(f"official validation: {error}" for error in official_validation["errors"])
    blockers.extend(f"official coverage: {blocker}" for blocker in official_coverage["blockers"])

    if draft_label_rows and not official_label_rows:
        warnings.append("draft labels exist but have not been copied into the official reviewed-label file")
    if not draft_validation["ok"]:
        warnings.extend(f"draft validation: {error}" for error in draft_validation["errors"])

    formal_promotion_ready = not blockers

    return {
        "formal_promotion_ready": formal_promotion_ready,
        "blockers": blockers,
        "warnings": warnings,
        "official": {
            "label_count": len(official_label_rows),
            "accepted_count": official_validation["accepted_count"],
            "rejected_count": official_validation["rejected_count"],
            "decision_counts": _label_counts(official_label_rows),
            "validation_ok": official_validation["ok"],
            "validation_errors": official_validation["errors"],
            "projected_formal_count": official_coverage["projected_formal_count"],
            "coverage_blockers": official_coverage["blockers"],
            "class_projection": official_coverage["projected_counts_after_accepts"],
            "remaining_deficits": official_coverage["deficits_after_accepts"],
        },
        "draft": {
            "label_count": len(draft_label_rows),
            "accepted_count": draft_validation["accepted_count"],
            "rejected_count": draft_validation["rejected_count"],
            "decision_counts": _label_counts(draft_label_rows),
            "validation_ok": draft_validation["ok"],
            "validation_errors": draft_validation["errors"],
            "projected_formal_count": draft_coverage["projected_formal_count"],
            "coverage_blockers": draft_coverage["blockers"],
            "class_projection": draft_coverage["projected_counts_after_accepts"],
            "remaining_deficits": draft_coverage["deficits_after_accepts"],
        },
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Label Promotion Audit",
        "",
        "This report is read-only. It does not modify formal gold, official labels, or split files.",
        "",
        "## Decision",
        "",
        f"- Formal promotion ready: `{str(audit['formal_promotion_ready']).lower()}`",
        "",
        "## Official Reviewed Labels",
        "",
        f"- Rows: {audit['official']['label_count']}",
        f"- Accepted: {audit['official']['accepted_count']}",
        f"- Rejected: {audit['official']['rejected_count']}",
        f"- Projected formal count: {audit['official']['projected_formal_count']}",
        f"- Validation OK: `{str(audit['official']['validation_ok']).lower()}`",
        "",
        "## Draft Reviewed Labels",
        "",
        f"- Rows: {audit['draft']['label_count']}",
        f"- Accepted: {audit['draft']['accepted_count']}",
        f"- Rejected: {audit['draft']['rejected_count']}",
        f"- Projected formal count: {audit['draft']['projected_formal_count']}",
        f"- Validation OK: `{str(audit['draft']['validation_ok']).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    if audit["blockers"]:
        lines.extend(f"- {blocker}" for blocker in audit["blockers"])
    else:
        lines.append("- None for formal reviewed-label promotion.")

    lines.extend(["", "## Warnings", ""])
    if audit["warnings"]:
        lines.extend(f"- {warning}" for warning in audit["warnings"])
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Official Class Projection",
            "",
            "| Case type | Projected formal | Remaining deficit |",
            "| --- | ---: | ---: |",
        ]
    )
    for case_type, projected in audit["official"]["class_projection"].items():
        deficit = audit["official"]["remaining_deficits"].get(case_type, 0)
        lines.append(f"| `{case_type}` | {projected} | {deficit} |")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not promote draft labels without manual confirmation.",
            "- Do not create official train/held-out splits from preview artifacts.",
            "- Do not run automatic tuning until official split and baseline gates pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_promotion_audit(
    gold_path: str | Path,
    candidates_path: str | Path,
    official_labels_path: str | Path,
    draft_labels_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> dict[str, Any]:
    audit = audit_promotion_readiness(
        load_jsonl(gold_path),
        load_jsonl(candidates_path),
        load_jsonl(official_labels_path),
        load_jsonl(draft_labels_path),
        targets=targets,
        target_total=target_total,
    )
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(audit), encoding="utf-8")
    _write_json(json_report_path, audit)
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--official-labels", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--draft-labels", default="eval/gold/reviewed_labels_draft_20260622.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.json")
    args = parser.parse_args(argv)

    audit = write_promotion_audit(
        args.gold,
        args.candidates,
        args.official_labels,
        args.draft_labels,
        args.report,
        args.json_report,
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["formal_promotion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
