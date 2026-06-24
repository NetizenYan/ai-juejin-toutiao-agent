"""Apply a human-confirmed reviewed-label promotion.

This is the only script allowed to copy the official-shape preview into the
official reviewed-label file, and it requires an exact confirmation token.
It creates a backup before writing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plan_reviewed_labels_promotion import load_jsonl, sha256_file
from scripts.validate_gold_reviewed_labels import validate_reviewed_labels


CONFIRMATION_TOKEN = "COPY_REVIEWED_LABELS_20260622"


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


def _backup_path(official_path: Path, backup_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return backup_dir / f"{official_path.stem}.backup_before_promotion_{timestamp}{official_path.suffix}"


def apply_reviewed_labels_promotion(
    preview_path: str | Path,
    official_path: str | Path,
    backup_dir: str | Path,
    *,
    confirm: str,
    candidates_path: str | Path | None = None,
    allow_nonempty_official: bool = False,
) -> dict[str, Any]:
    preview = Path(preview_path)
    official = Path(official_path)
    backup_root = Path(backup_dir)
    blockers: list[str] = []
    warnings: list[str] = []
    backup = {"created": False, "path": None, "sha256": None}

    if confirm != CONFIRMATION_TOKEN:
        blockers.append("confirmation token mismatch")
    if not preview.exists():
        blockers.append("preview reviewed-label file is missing")
    elif not load_jsonl(preview):
        blockers.append("preview reviewed-label file has no rows")
    if not official.exists():
        blockers.append("official reviewed-label file is missing")
    elif load_jsonl(official) and not allow_nonempty_official:
        blockers.append("official reviewed-label file already has rows")

    validation: dict[str, Any] | None = None
    if candidates_path is not None and preview.exists():
        result = validate_reviewed_labels(candidates_path, preview)
        validation = asdict(result)
        if not result.ok:
            blockers.extend(f"preview validation: {error}" for error in result.errors)

    before = _file_state(official)
    preview_state = _file_state(preview)
    if blockers:
        return {
            "applied": False,
            "confirmation_token": "matched" if confirm == CONFIRMATION_TOKEN else "mismatch",
            "preview": preview_state,
            "official_before": before,
            "official_after": before,
            "backup": backup,
            "validation": validation,
            "blockers": blockers,
            "warnings": warnings,
        }

    backup_root.mkdir(parents=True, exist_ok=True)
    backup_file = _backup_path(official, backup_root)
    shutil.copyfile(official, backup_file)
    backup = {
        "created": True,
        "path": str(backup_file),
        "sha256": sha256_file(backup_file),
    }
    shutil.copyfile(preview, official)
    after = _file_state(official)

    return {
        "applied": True,
        "confirmation_token": "matched",
        "preview": preview_state,
        "official_before": before,
        "official_after": after,
        "backup": backup,
        "validation": validation,
        "blockers": blockers,
        "warnings": warnings,
    }


def write_apply_report(result: dict[str, Any], report_path: str | Path, json_report_path: str | Path) -> None:
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Reviewed Label Promotion Apply Report",
        "",
        "This report records a guarded apply attempt.",
        "",
        "## Decision",
        "",
        f"- Applied: `{str(result['applied']).lower()}`",
        f"- Confirmation token: `{result['confirmation_token']}`",
        f"- Backup created: `{str(result['backup']['created']).lower()}`",
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
    lines.extend(["", "## Guardrails", "", "- Keep automatic tuning disabled until official splits and baselines exist."])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--official", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--backup-dir", default="eval/gold/backups")
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--allow-nonempty-official", action="store_true")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.json")
    args = parser.parse_args(argv)

    result = apply_reviewed_labels_promotion(
        args.preview,
        args.official,
        args.backup_dir,
        confirm=args.confirm,
        candidates_path=args.candidates,
        allow_nonempty_official=args.allow_nonempty_official,
    )
    write_apply_report(result, args.report, args.json_report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["applied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
