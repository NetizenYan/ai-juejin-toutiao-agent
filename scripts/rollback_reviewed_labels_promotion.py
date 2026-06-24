"""Rollback reviewed-label promotion from the apply backup.

This script is guarded by an exact rollback token. It restores the official
reviewed-label file from the backup recorded by a successful apply report, and
backs up the current official file before restoring.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plan_reviewed_labels_promotion import load_jsonl, sha256_file


ROLLBACK_CONFIRMATION_TOKEN = "ROLLBACK_REVIEWED_LABELS_20260622"


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_state(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    rows: list[dict[str, Any]] = []
    parse_error: str | None = None
    if input_path.exists():
        try:
            rows = load_jsonl(input_path)
        except (json.JSONDecodeError, ValueError) as exc:
            parse_error = str(exc)
    return {
        "path": str(input_path),
        "exists": input_path.exists(),
        "bytes": input_path.stat().st_size if input_path.exists() else 0,
        "sha256": sha256_file(input_path),
        "row_count": len(rows),
        "parse_error": parse_error,
    }


def _current_backup_path(official_path: Path, rollback_backup_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return rollback_backup_dir / f"{official_path.stem}.backup_before_rollback_{timestamp}{official_path.suffix}"


def rollback_reviewed_labels_promotion(
    apply_report_path: str | Path,
    official_path: str | Path,
    rollback_backup_dir: str | Path,
    *,
    confirm: str,
) -> dict[str, Any]:
    official = Path(official_path)
    rollback_dir = Path(rollback_backup_dir)
    apply_report = _load_json(apply_report_path)
    backup_info = apply_report.get("backup") or {}
    apply_backup_path = Path(str(backup_info.get("path") or ""))
    blockers: list[str] = []
    current_backup = {"created": False, "path": None, "sha256": None}

    if confirm != ROLLBACK_CONFIRMATION_TOKEN:
        blockers.append("confirmation token mismatch")
    if not apply_report.get("applied", False):
        blockers.append("apply report was not applied")
    if not backup_info.get("created", False):
        blockers.append("apply report has no created backup")
    if not backup_info.get("path"):
        blockers.append("apply report backup path is missing")
    elif not apply_backup_path.exists():
        blockers.append(f"apply backup file does not exist: {apply_backup_path}")
    if not official.exists():
        blockers.append("official reviewed-label file is missing")

    before = _file_state(official)
    if blockers:
        return {
            "rolled_back": False,
            "confirmation_token": "matched" if confirm == ROLLBACK_CONFIRMATION_TOKEN else "mismatch",
            "apply_report_path": str(apply_report_path),
            "apply_backup": _file_state(apply_backup_path) if backup_info.get("path") else None,
            "official_before": before,
            "official_after": before,
            "current_backup": current_backup,
            "blockers": blockers,
        }

    rollback_dir.mkdir(parents=True, exist_ok=True)
    current_backup_path = _current_backup_path(official, rollback_dir)
    shutil.copyfile(official, current_backup_path)
    current_backup = {
        "created": True,
        "path": str(current_backup_path),
        "sha256": sha256_file(current_backup_path),
    }
    shutil.copyfile(apply_backup_path, official)
    after = _file_state(official)
    return {
        "rolled_back": True,
        "confirmation_token": "matched",
        "apply_report_path": str(apply_report_path),
        "apply_backup": _file_state(apply_backup_path),
        "official_before": before,
        "official_after": after,
        "current_backup": current_backup,
        "blockers": [],
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Label Promotion Rollback",
        "",
        "This report records a guarded rollback attempt.",
        "",
        "## Decision",
        "",
        f"- Rolled back: `{str(result['rolled_back']).lower()}`",
        f"- Confirmation token: `{result['confirmation_token']}`",
        f"- Current official backup created: `{str(result['current_backup']['created']).lower()}`",
        "",
        "## Official Labels",
        "",
        f"- Before rows: {result['official_before']['row_count']}",
        f"- After rows: {result['official_after']['row_count']}",
        f"- After SHA-256: `{result['official_after']['sha256']}`",
        "",
        "## Blockers",
        "",
    ]
    if result["blockers"]:
        lines.extend(f"- {blocker}" for blocker in result["blockers"])
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Use rollback only for a confirmed bad apply.",
            "- Rerun reviewed-label validation and pipeline state after rollback.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_rollback_report(
    apply_report_path: str | Path,
    official_path: str | Path,
    rollback_backup_dir: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    *,
    confirm: str,
) -> dict[str, Any]:
    result = rollback_reviewed_labels_promotion(
        apply_report_path,
        official_path,
        rollback_backup_dir,
        confirm=confirm,
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
    parser.add_argument("--apply-report", default="eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.json")
    parser.add_argument("--official", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--rollback-backup-dir", default="eval/gold/backups")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.json")
    args = parser.parse_args(argv)

    result = write_rollback_report(
        args.apply_report,
        args.official,
        args.rollback_backup_dir,
        args.report,
        args.json_report,
        confirm=args.confirm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["rolled_back"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
