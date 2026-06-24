"""Simulate reviewed-label promotion in a sandbox.

The real official reviewed-label file is never modified. This tool copies the
current official file into a sandbox, applies the official-shape preview there,
and runs the pipeline-state checker against the sandbox copy.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_reviewed_labels_promotion import (
    CONFIRMATION_TOKEN,
    apply_reviewed_labels_promotion,
)
from scripts.check_reviewed_label_pipeline_state import assess_pipeline_state
from scripts.plan_reviewed_labels_promotion import load_jsonl, sha256_file
from scripts.report_reviewed_label_coverage import DEFAULT_TARGETS, DEFAULT_TARGET_TOTAL


def _file_state(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    rows = load_jsonl(input_path) if input_path.exists() else []
    return {
        "path": str(input_path),
        "exists": input_path.exists(),
        "bytes": input_path.stat().st_size if input_path.exists() else 0,
        "sha256": sha256_file(input_path),
        "row_count": len(rows),
    }


def simulate_reviewed_labels_promotion(
    gold_path: str | Path,
    candidates_path: str | Path,
    preview_path: str | Path,
    official_path: str | Path,
    sandbox_dir: str | Path,
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> dict[str, Any]:
    gold = Path(gold_path)
    candidates = Path(candidates_path)
    preview = Path(preview_path)
    official = Path(official_path)
    sandbox = Path(sandbox_dir)
    sandbox.mkdir(parents=True, exist_ok=True)

    real_before = _file_state(official)
    sandbox_official = sandbox / f"{official.stem}.sandbox{official.suffix}"
    sandbox_backup_dir = sandbox / "backups"
    if official.exists():
        shutil.copyfile(official, sandbox_official)
    else:
        sandbox_official.write_text("", encoding="utf-8")

    apply_result = apply_reviewed_labels_promotion(
        preview,
        sandbox_official,
        sandbox_backup_dir,
        confirm=CONFIRMATION_TOKEN,
        candidates_path=candidates,
    )

    pipeline_state: dict[str, Any] | None = None
    if apply_result["applied"]:
        pipeline_state = assess_pipeline_state(
            gold,
            candidates,
            sandbox_official,
            preview_labels_path=preview,
            targets=targets if targets is not None else DEFAULT_TARGETS,
            target_total=target_total,
        )

    real_after = _file_state(official)
    blockers = list(apply_result.get("blockers") or [])
    if pipeline_state and not pipeline_state["reviewed_labels_ready_for_gold_expansion"]:
        blockers.extend(f"sandbox pipeline: {blocker}" for blocker in pipeline_state["blockers"])

    return {
        "sandbox_only": True,
        "simulation_applied": bool(apply_result["applied"]),
        "real_official_unchanged": real_before["sha256"] == real_after["sha256"]
        and real_before["bytes"] == real_after["bytes"],
        "real_official_before": real_before,
        "real_official_after": real_after,
        "sandbox_official": _file_state(sandbox_official),
        "apply_result": apply_result,
        "pipeline_state": pipeline_state,
        "blockers": blockers,
        "next_actions": [
            "if the simulation is ready, human confirmation is still required before writing the real official file",
            "after real promotion, rerun pipeline state, coverage, promotion audit, expanded preview, and tuning gate checks",
        ],
    }


def render_markdown(result: dict[str, Any]) -> str:
    pipeline_state = result.get("pipeline_state") or {}
    stage = pipeline_state.get("reviewed_label_stage", "not_available")
    ready = pipeline_state.get("reviewed_labels_ready_for_gold_expansion", False)
    gate = (pipeline_state.get("automatic_tuning_gate") or {}).get("ok")
    gate_text = "open" if gate else "closed"
    lines = [
        "# Reviewed Label Promotion Sandbox Simulation",
        "",
        "Sandbox only. This report does not modify the real official reviewed-label file.",
        "",
        "## Decision",
        "",
        f"- Simulation applied: `{str(result['simulation_applied']).lower()}`",
        f"- Real official unchanged: `{str(result['real_official_unchanged']).lower()}`",
        f"- Sandbox stage: `{stage}`",
        f"- Sandbox ready for gold expansion: `{str(ready).lower()}`",
        f"- Automatic tuning gate after sandbox apply: `{gate_text}`",
        "",
        "## Real Official File",
        "",
        f"- Before rows: {result['real_official_before']['row_count']}",
        f"- After rows: {result['real_official_after']['row_count']}",
        f"- After SHA-256: `{result['real_official_after']['sha256']}`",
        "",
        "## Sandbox Official File",
        "",
        f"- Path: `{result['sandbox_official']['path']}`",
        f"- Rows: {result['sandbox_official']['row_count']}",
        f"- SHA-256: `{result['sandbox_official']['sha256']}`",
        "",
        "## Blockers",
        "",
    ]
    if result["blockers"]:
        lines.extend(f"- {blocker}" for blocker in result["blockers"])
    else:
        lines.append("- None for sandbox reviewed-label gold-expansion readiness.")

    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {action}" for action in result["next_actions"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This simulation is not manual approval.",
            "- Do not run automatic tuning while the real gate is closed.",
            "- Do not treat sandbox files as official reviewed labels.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_simulation_report(
    gold_path: str | Path,
    candidates_path: str | Path,
    preview_path: str | Path,
    official_path: str | Path,
    sandbox_dir: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
) -> dict[str, Any]:
    result = simulate_reviewed_labels_promotion(
        gold_path,
        candidates_path,
        preview_path,
        official_path,
        sandbox_dir,
        targets=targets,
        target_total=target_total,
    )
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(result), encoding="utf-8")
    json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--preview", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--official", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--sandbox-dir", default="eval/gold/sandbox/promotion_20260622")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.json")
    args = parser.parse_args(argv)

    result = write_simulation_report(
        args.gold,
        args.candidates,
        args.preview,
        args.official,
        args.sandbox_dir,
        args.report,
        args.json_report,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["simulation_applied"] and not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
