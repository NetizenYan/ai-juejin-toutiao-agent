"""Plan a reviewed-label promotion transaction without modifying official files.

This tool is intentionally dry-run only. It checks whether the reviewed-label
official preview is ready for a human-approved promotion into the formal
reviewed-label file, then writes a transaction plan and audit JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


DECISIONS = ("accept_as_gold", "merge_with_existing", "needs_evidence_lookup", "reject")


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


def sha256_file(path: str | Path) -> str | None:
    input_path = Path(path)
    if not input_path.exists():
        return None
    digest = hashlib.sha256()
    with input_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_summary(path: str | Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    input_path = Path(path)
    decision_counter = Counter(str(row.get("decision", "")) for row in rows)
    return {
        "path": str(input_path),
        "exists": input_path.exists(),
        "bytes": input_path.stat().st_size if input_path.exists() else 0,
        "sha256": sha256_file(input_path),
        "row_count": len(rows),
        "decision_counts": {decision: decision_counter.get(decision, 0) for decision in DECISIONS},
    }


def plan_promotion_transaction(preview_path: str | Path, official_path: str | Path) -> dict[str, Any]:
    preview_rows = load_jsonl(preview_path)
    official_rows = load_jsonl(official_path)
    preview = _file_summary(preview_path, preview_rows)
    official = _file_summary(official_path, official_rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not preview["exists"]:
        blockers.append("preview reviewed-label file is missing")
    elif preview["row_count"] == 0:
        blockers.append("preview reviewed-label file has no rows")

    if not official["exists"]:
        blockers.append("official reviewed-label file is missing")
    elif official["row_count"] != 0:
        blockers.append("official reviewed-label file already has rows; inspect before replacement")

    if preview["exists"] and official["exists"] and preview["sha256"] == official["sha256"]:
        warnings.append("preview and official files already have the same hash")

    manual_transaction_ready = not blockers
    actions = [
        "manual confirmation required before copying the preview into the official reviewed-label file",
        "validate the preview against the gray candidate source",
        "back up the current official reviewed-label file and record its hash",
        "after human approval only, copy the preview file content into the official reviewed-label file",
        "rerun reviewed-label validation, coverage, promotion audit, split preview, and the tuning gate check",
        "keep automatic tuning closed until official train/held-out splits and baseline reports exist",
    ]

    return {
        "dry_run_only": True,
        "manual_transaction_ready": manual_transaction_ready,
        "preview": preview,
        "official": official,
        "blockers": blockers,
        "warnings": warnings,
        "actions": actions,
    }


def render_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Label Promotion Transaction Dry-Run",
        "",
        "Dry-run only. This report does not modify the official reviewed-label file.",
        "",
        "## Decision",
        "",
        f"- Manual transaction ready: `{str(plan['manual_transaction_ready']).lower()}`",
        f"- Dry-run only: `{str(plan['dry_run_only']).lower()}`",
        "",
        "## Preview File",
        "",
        f"- Path: `{plan['preview']['path']}`",
        f"- Exists: `{str(plan['preview']['exists']).lower()}`",
        f"- Rows: {plan['preview']['row_count']}",
        f"- Bytes: {plan['preview']['bytes']}",
        f"- SHA-256: `{plan['preview']['sha256']}`",
        "",
        "## Official File",
        "",
        f"- Path: `{plan['official']['path']}`",
        f"- Exists: `{str(plan['official']['exists']).lower()}`",
        f"- Rows: {plan['official']['row_count']}",
        f"- Bytes: {plan['official']['bytes']}",
        f"- SHA-256: `{plan['official']['sha256']}`",
        "",
        "## Preview Decision Counts",
        "",
        "| Decision | Rows |",
        "| --- | ---: |",
    ]
    for decision, count in plan["preview"]["decision_counts"].items():
        lines.append(f"| `{decision}` | {count} |")

    lines.extend(["", "## Blockers", ""])
    if plan["blockers"]:
        lines.extend(f"- {blocker}" for blocker in plan["blockers"])
    else:
        lines.append("- None for the manual reviewed-label promotion transaction.")

    lines.extend(["", "## Warnings", ""])
    if plan["warnings"]:
        lines.extend(f"- {warning}" for warning in plan["warnings"])
    else:
        lines.append("- None.")

    lines.extend(["", "## Required Manual Actions", ""])
    lines.extend(f"{idx}. {action}" for idx, action in enumerate(plan["actions"], start=1))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This tool has no apply mode.",
            "- Do not create official split files from preview-only artifacts.",
            "- Do not run automatic tuning until the official gate is open.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_promotion_plan(
    preview_path: str | Path,
    official_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
) -> dict[str, Any]:
    plan = plan_promotion_transaction(preview_path, official_path)
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(plan), encoding="utf-8")
    json_report.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--official", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.md")
    parser.add_argument(
        "--json-report",
        default="eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.json",
    )
    args = parser.parse_args(argv)

    plan = write_promotion_plan(args.preview, args.official, args.report, args.json_report)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["manual_transaction_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
