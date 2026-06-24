"""Check reviewed-label pipeline state after, or before, manual confirmation.

This read-only checker answers three questions:

1. Has the official reviewed-label file been manually confirmed yet?
2. If confirmed, are reviewed labels ready to build the expanded gold preview?
3. Is automatic tuning still blocked by formal gold, split, or baseline gates?
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_gold_promotion_readiness import validate_reviewed_labels_from_rows
from scripts.check_gold_tuning_gate import check_tuning_gate
from scripts.plan_reviewed_labels_promotion import sha256_file
from scripts.report_reviewed_label_coverage import (
    DEFAULT_TARGETS,
    DEFAULT_TARGET_TOTAL,
    load_jsonl,
    summarize_reviewed_label_coverage,
)


def _decision_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row.get("decision", "")) for row in rows)
    return {
        "accept_as_gold": counter.get("accept_as_gold", 0),
        "merge_with_existing": counter.get("merge_with_existing", 0),
        "needs_evidence_lookup": counter.get("needs_evidence_lookup", 0),
        "reject": counter.get("reject", 0),
    }


def _file_state(path: str | Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    input_path = Path(path)
    return {
        "path": str(input_path),
        "exists": input_path.exists(),
        "bytes": input_path.stat().st_size if input_path.exists() else 0,
        "sha256": sha256_file(input_path),
        "row_count": len(rows),
        "decision_counts": _decision_counts(rows),
    }


def _formal_counts(gold_rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row.get("case_type", "UNKNOWN")) for row in gold_rows)
    return dict(counter)


def assess_pipeline_state(
    gold_path: str | Path,
    candidates_path: str | Path,
    official_labels_path: str | Path,
    *,
    preview_labels_path: str | Path | None = None,
    train_split_path: str | Path | None = None,
    heldout_split_path: str | Path | None = None,
    train_report_path: str | Path | None = None,
    heldout_report_path: str | Path | None = None,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> dict[str, Any]:
    gold_rows = load_jsonl(gold_path)
    candidate_rows = load_jsonl(candidates_path)
    official_rows = load_jsonl(official_labels_path)
    preview_rows = load_jsonl(preview_labels_path) if preview_labels_path else []

    validation = validate_reviewed_labels_from_rows(candidate_rows, official_rows)
    coverage = summarize_reviewed_label_coverage(
        gold_rows,
        official_rows,
        targets=targets if targets is not None else DEFAULT_TARGETS,
        target_total=target_total,
    )
    coverage_dict = asdict(coverage)
    tuning_gate = asdict(
        check_tuning_gate(
            {
                "formal_count": len(gold_rows),
                "formal_counts": _formal_counts(gold_rows),
            },
            train_split_path=train_split_path,
            heldout_split_path=heldout_split_path,
            train_report_path=train_report_path,
            heldout_report_path=heldout_report_path,
        )
    )

    blockers: list[str] = []
    warnings: list[str] = []

    if not official_rows:
        blockers.append("official reviewed-label file has no rows")
    if not validation["ok"]:
        blockers.extend(f"official validation: {error}" for error in validation["errors"])
    blockers.extend(f"official coverage: {blocker}" for blocker in coverage.blockers)

    official = _file_state(official_labels_path, official_rows)
    preview = _file_state(preview_labels_path, preview_rows) if preview_labels_path else None
    if preview and official_rows and preview_rows and official["sha256"] != preview["sha256"]:
        warnings.append("official reviewed-label file hash differs from the official-shape preview")

    ready_for_gold_expansion = bool(official_rows) and validation["ok"] and not coverage.blockers
    if not official_rows:
        stage = "pending_manual_confirmation"
    elif ready_for_gold_expansion:
        stage = "reviewed_labels_ready_for_gold_expansion"
    else:
        stage = "reviewed_labels_need_fix"

    next_actions = []
    if stage == "pending_manual_confirmation":
        next_actions.append("manual confirmation is still required before official reviewed labels can drive gold expansion")
    elif stage == "reviewed_labels_ready_for_gold_expansion":
        next_actions.append("build the expanded gold preview from official reviewed labels")
        next_actions.append("create official train and held-out splits only after formal gold is updated")
    else:
        next_actions.append("fix reviewed-label validation or coverage blockers before gold expansion")
    if not tuning_gate["ok"]:
        next_actions.append("keep automatic tuning disabled until the tuning gate returns ok=true")

    return {
        "reviewed_label_stage": stage,
        "reviewed_labels_ready_for_gold_expansion": ready_for_gold_expansion,
        "official": official,
        "preview": preview,
        "validation": validation,
        "coverage": coverage_dict,
        "automatic_tuning_gate": tuning_gate,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": next_actions,
    }


def render_markdown(state: dict[str, Any]) -> str:
    gate_state = "open" if state["automatic_tuning_gate"]["ok"] else "closed"
    lines = [
        "# Reviewed Label Pipeline State",
        "",
        "This report is read-only. It does not modify official labels, formal gold, split files, or tuning config.",
        "",
        "## Decision",
        "",
        f"- Reviewed-label stage: `{state['reviewed_label_stage']}`",
        f"- Ready for gold expansion: `{str(state['reviewed_labels_ready_for_gold_expansion']).lower()}`",
        f"- Automatic tuning gate: `{gate_state}`",
        "",
        "## Official Reviewed Labels",
        "",
        f"- Path: `{state['official']['path']}`",
        f"- Rows: {state['official']['row_count']}",
        f"- Bytes: {state['official']['bytes']}",
        f"- SHA-256: `{state['official']['sha256']}`",
        f"- Validation OK: `{str(state['validation']['ok']).lower()}`",
        "",
        "## Coverage Projection From Official Labels",
        "",
        f"- Formal gold count now: {state['coverage']['formal_count']}",
        f"- Official reviewed-label rows: {state['coverage']['label_count']}",
        f"- Accepted rows: {state['coverage']['accepted_count']}",
        f"- Merge rows: {state['coverage']['merge_count']}",
        f"- Projected formal count after accepts: {state['coverage']['projected_formal_count']}",
        "",
        "## Blockers",
        "",
    ]
    if state["blockers"]:
        lines.extend(f"- {blocker}" for blocker in state["blockers"])
    else:
        lines.append("- None for reviewed-label gold-expansion readiness.")

    lines.extend(["", "## Automatic Tuning Gate Blockers", ""])
    if state["automatic_tuning_gate"]["blockers"]:
        lines.extend(f"- {blocker}" for blocker in state["automatic_tuning_gate"]["blockers"])
    else:
        lines.append("- None.")

    lines.extend(["", "## Warnings", ""])
    if state["warnings"]:
        lines.extend(f"- {warning}" for warning in state["warnings"])
    else:
        lines.append("- None.")

    lines.extend(["", "## Next Actions", ""])
    for action in state["next_actions"]:
        if action.startswith("manual confirmation"):
            lines.append("- Manual confirmation is still required before official labels can drive gold expansion.")
        else:
            lines.append(f"- {action}")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not run automatic tuning while the gate is closed.",
            "- Do not treat preview artifacts as official split files.",
            "- Do not install `sentence-transformers` for this 3.3 gate work.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_pipeline_state_report(
    gold_path: str | Path,
    candidates_path: str | Path,
    official_labels_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    state = assess_pipeline_state(gold_path, candidates_path, official_labels_path, **kwargs)
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(state), encoding="utf-8")
    json_report.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--official-labels", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--preview-labels", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--train-split", default="eval/gold/splits/retrieval_train_20260622.jsonl")
    parser.add_argument("--heldout-split", default="eval/gold/splits/retrieval_heldout_20260622.jsonl")
    parser.add_argument("--train-report", default="eval/reports/3_3/train_baseline_3_2E.json")
    parser.add_argument("--heldout-report", default="eval/reports/3_3/heldout_baseline_3_2E.json")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.json")
    args = parser.parse_args(argv)

    state = write_pipeline_state_report(
        args.gold,
        args.candidates,
        args.official_labels,
        args.report,
        args.json_report,
        preview_labels_path=args.preview_labels,
        train_split_path=args.train_split,
        heldout_split_path=args.heldout_split,
        train_report_path=args.train_report,
        heldout_report_path=args.heldout_report,
    )
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state["reviewed_labels_ready_for_gold_expansion"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
