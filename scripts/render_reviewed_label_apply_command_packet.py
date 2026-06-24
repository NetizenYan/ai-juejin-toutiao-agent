"""Render the human confirmation command packet for reviewed-label promotion.

This script does not execute the apply command. It packages the exact command
and follow-up verification commands after the apply preflight is ready.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_reviewed_labels_promotion import CONFIRMATION_TOKEN


DEFAULT_PATHS = {
    "gold": "eval/gold/eval_gold_retrieval.jsonl",
    "candidates": "eval/gold/gray_candidates_20260622.jsonl",
    "preview": "eval/gold/reviewed_labels_official_preview_20260622.jsonl",
    "official": "eval/gold/reviewed_labels_20260622.jsonl",
    "backup_dir": "eval/gold/backups",
    "sandbox_dir": "eval/gold/sandbox/apply_preflight_20260622",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ps(command: str) -> str:
    return command.replace("/", "\\")


def _paths_from_preflight(preflight: dict[str, Any]) -> dict[str, str]:
    plan = preflight.get("promotion_plan") or {}
    preview = (plan.get("preview") or {}).get("path") or DEFAULT_PATHS["preview"]
    official = (plan.get("official") or {}).get("path") or DEFAULT_PATHS["official"]
    return {
        **DEFAULT_PATHS,
        "preview": preview,
        "official": official,
    }


def build_command_packet(preflight_path: str | Path) -> dict[str, Any]:
    preflight = _load_json(preflight_path)
    paths = _paths_from_preflight(preflight)
    blockers: list[str] = []
    if not preflight.get("apply_ready", False):
        blockers.append("preflight is not apply_ready")
        blockers.extend(str(blocker) for blocker in preflight.get("blockers", []))

    apply_command = _ps(
        "python scripts/apply_reviewed_labels_promotion.py "
        f"--preview {paths['preview']} "
        f"--official {paths['official']} "
        f"--backup-dir {paths['backup_dir']} "
        f"--candidates {paths['candidates']} "
        f"--confirm {CONFIRMATION_TOKEN} "
        "--report eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.md "
        "--json-report eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.json"
    )
    post_apply_commands = [
        _ps(
            "python scripts/validate_gold_reviewed_labels.py "
            f"--candidates {paths['candidates']} --labels {paths['official']}"
        ),
        _ps(
            "python scripts/check_reviewed_label_conditions.py "
            f"--labels {paths['official']} "
            "--evidence-corpus work/econ_rag_experiment/clean_merged_recent_econ.jsonl "
            "--report eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md "
            "--json-report eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.json"
        ),
        _ps(
            "python scripts/check_reviewed_label_pipeline_state.py "
            f"--gold {paths['gold']} --candidates {paths['candidates']} "
            f"--official-labels {paths['official']} --preview-labels {paths['preview']} "
            "--report eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md "
            "--json-report eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.json"
        ),
        _ps(
            "python scripts/report_reviewed_label_coverage.py "
            f"--gold {paths['gold']} --labels {paths['official']} "
            "--report eval/gold/REVIEWED_LABEL_COVERAGE_20260622.md "
            "--json-report eval/gold/REVIEWED_LABEL_COVERAGE_20260622.json"
        ),
        _ps(
            "python scripts/audit_gold_promotion_readiness.py "
            f"--gold {paths['gold']} --candidates {paths['candidates']} "
            f"--official-labels {paths['official']} "
            "--draft-labels eval/gold/reviewed_labels_draft_20260622.jsonl "
            "--report eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md "
            "--json-report eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.json"
        ),
        _ps(
            "python scripts/build_expanded_gold_preview.py "
            f"--gold {paths['gold']} --labels {paths['official']} "
            "--output eval/gold/eval_gold_retrieval_expanded_preview_20260622.jsonl "
            "--summary eval/gold/eval_gold_retrieval_expanded_preview_20260622.json"
        ),
        _ps("python scripts/check_gold_tuning_gate.py --coverage eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json"),
    ]

    promotion_plan = preflight.get("promotion_plan") or {}
    sandbox_pipeline = ((preflight.get("sandbox") or {}).get("pipeline_state") or {})
    coverage = sandbox_pipeline.get("coverage") or {}
    return {
        "packet_ready": not blockers,
        "preflight_path": str(preflight_path),
        "confirmation_token": CONFIRMATION_TOKEN,
        "requires_human_confirmation": True,
        "apply_command": apply_command,
        "post_apply_commands": post_apply_commands,
        "preview": promotion_plan.get("preview", {}),
        "official_before": promotion_plan.get("official", {}),
        "sandbox_projection": {
            "stage": sandbox_pipeline.get("reviewed_label_stage"),
            "projected_formal_count": coverage.get("projected_formal_count"),
            "deficits_after_accepts": coverage.get("deficits_after_accepts"),
        },
        "blockers": blockers,
        "guardrails": [
            "Do not run the apply command without explicit human approval.",
            "Do not run automatic tuning after apply; first update formal gold, splits, and baselines.",
            "Do not install sentence-transformers for this apply step.",
        ],
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Manual Confirmation Command Packet",
        "",
        "This packet is a command review aid. It does not execute any command.",
        "",
        "## Decision",
        "",
        f"- Packet ready: `{str(packet['packet_ready']).lower()}`",
        f"- Requires human confirmation: `{str(packet['requires_human_confirmation']).lower()}`",
        f"- Confirmation token: `{packet['confirmation_token']}`",
        "",
        "## Apply Command",
        "",
        "```powershell",
        packet["apply_command"],
        "```",
        "",
        "## Post-Apply Verification Commands",
        "",
    ]
    for command in packet["post_apply_commands"]:
        lines.extend(["```powershell", command, "```", ""])

    lines.extend(["## Current Evidence", ""])
    lines.extend(
        [
            f"- Preview rows: {packet['preview'].get('row_count')}",
            f"- Preview SHA-256: `{packet['preview'].get('sha256')}`",
            f"- Official rows before apply: {packet['official_before'].get('row_count')}",
            f"- Official SHA-256 before apply: `{packet['official_before'].get('sha256')}`",
            f"- Sandbox stage: `{packet['sandbox_projection'].get('stage')}`",
            f"- Sandbox projected formal count: {packet['sandbox_projection'].get('projected_formal_count')}",
            "",
            "## Blockers",
            "",
        ]
    )
    if packet["blockers"]:
        lines.extend(f"- {blocker}" for blocker in packet["blockers"])
    else:
        lines.append("- None in preflight. Explicit human confirmation is still required.")
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- {guardrail}" for guardrail in packet["guardrails"])
    return "\n".join(lines) + "\n"


def write_command_packet(
    preflight_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
) -> dict[str, Any]:
    packet = build_command_packet(preflight_path)
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(packet), encoding="utf-8")
    json_report.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", default="eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.json")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.json")
    args = parser.parse_args(argv)

    packet = write_command_packet(args.preflight, args.report, args.json_report)
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0 if packet["packet_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
