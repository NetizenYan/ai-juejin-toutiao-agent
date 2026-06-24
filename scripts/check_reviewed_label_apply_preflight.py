"""Check whether reviewed-label promotion is ready for explicit human apply.

This preflight is read-only for the real official reviewed-label file. It
validates the preview, runs the promotion dry-run checks, runs a sandbox apply,
and verifies that forbidden automatic-tuning state has not appeared early.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plan_reviewed_labels_promotion import plan_promotion_transaction
from scripts.report_reviewed_label_coverage import DEFAULT_TARGETS, DEFAULT_TARGET_TOTAL
from scripts.simulate_reviewed_labels_promotion import simulate_reviewed_labels_promotion
from scripts.check_reviewed_label_conditions import check_reviewed_label_conditions
from scripts.validate_gold_reviewed_labels import validate_reviewed_labels


def _exists(path: str | Path | None) -> bool:
    return bool(path) and Path(path).exists()


def check_apply_preflight(
    gold_path: str | Path,
    candidates_path: str | Path,
    preview_path: str | Path,
    official_path: str | Path,
    sandbox_dir: str | Path,
    *,
    targets: dict[str, int] | None = None,
    target_total: int = DEFAULT_TARGET_TOTAL,
    check_sentence_transformers: bool = True,
    tune_script_path: str | Path = "scripts/tune_rag_weights.py",
    train_split_path: str | Path = "eval/gold/splits/retrieval_train_20260622.jsonl",
    heldout_split_path: str | Path = "eval/gold/splits/retrieval_heldout_20260622.jsonl",
    condition_evidence_corpus_path: str | Path | None = "work/econ_rag_experiment/clean_merged_recent_econ.jsonl",
) -> dict[str, Any]:
    validation = asdict(validate_reviewed_labels(candidates_path, preview_path))
    conditional_approval = check_reviewed_label_conditions(
        preview_path,
        condition_evidence_corpus_path,
    )
    promotion_plan = plan_promotion_transaction(preview_path, official_path)
    sandbox = simulate_reviewed_labels_promotion(
        gold_path,
        candidates_path,
        preview_path,
        official_path,
        sandbox_dir,
        targets=targets if targets is not None else DEFAULT_TARGETS,
        target_total=target_total,
    )

    tune_script_exists = _exists(tune_script_path)
    train_split_exists = _exists(train_split_path)
    heldout_split_exists = _exists(heldout_split_path)
    sentence_transformers_installed = (
        importlib.util.find_spec("sentence_transformers") is not None
        if check_sentence_transformers
        else False
    )

    blockers: list[str] = []
    warnings: list[str] = []

    if not validation["ok"]:
        blockers.extend(f"preview validation: {error}" for error in validation["errors"])
    if not conditional_approval["ok"]:
        blockers.extend(
            f"conditional approval: {error}" for error in conditional_approval["errors"]
        )
    if not promotion_plan["manual_transaction_ready"]:
        blockers.extend(f"promotion plan: {blocker}" for blocker in promotion_plan["blockers"])
    if not sandbox["simulation_applied"]:
        blockers.extend(f"sandbox simulation: {blocker}" for blocker in sandbox["blockers"])
    if not sandbox["real_official_unchanged"]:
        blockers.append("sandbox simulation changed the real official reviewed-label file")
    pipeline_state = sandbox.get("pipeline_state") or {}
    if not pipeline_state.get("reviewed_labels_ready_for_gold_expansion", False):
        blockers.append("sandbox pipeline is not ready for gold expansion")
    if tune_script_exists:
        blockers.append(f"forbidden tuning script exists: {tune_script_path}")
    if train_split_exists:
        blockers.append(f"official train split exists before promotion: {train_split_path}")
    if heldout_split_exists:
        blockers.append(f"official held-out split exists before promotion: {heldout_split_path}")
    if sentence_transformers_installed:
        blockers.append("sentence_transformers is installed before the approved tuning phase")

    if promotion_plan["warnings"]:
        warnings.extend(f"promotion plan: {warning}" for warning in promotion_plan["warnings"])

    checks = {
        "preview_validation_ok": validation["ok"],
        "conditional_approval_ok": conditional_approval["ok"],
        "manual_transaction_ready": promotion_plan["manual_transaction_ready"],
        "sandbox_simulation_applied": sandbox["simulation_applied"],
        "sandbox_ready_for_gold_expansion": bool(
            pipeline_state.get("reviewed_labels_ready_for_gold_expansion", False)
        ),
        "real_official_unchanged": sandbox["real_official_unchanged"],
        "tune_script_absent": not tune_script_exists,
        "official_train_split_absent": not train_split_exists,
        "official_heldout_split_absent": not heldout_split_exists,
        "sentence_transformers_absent": not sentence_transformers_installed,
    }

    return {
        "apply_ready": not blockers,
        "checks": checks,
        "validation": validation,
        "conditional_approval": conditional_approval,
        "promotion_plan": promotion_plan,
        "sandbox": sandbox,
        "blockers": blockers,
        "warnings": warnings,
        "next_action": (
            "wait for explicit human confirmation token COPY_REVIEWED_LABELS_20260622"
            if not blockers
            else "fix blockers before requesting human confirmation"
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Label Apply Preflight",
        "",
        "Apply preflight. This report does not modify the real official reviewed-label file.",
        "",
        "## Decision",
        "",
        f"- Apply ready: `{str(result['apply_ready']).lower()}`",
        f"- Next action: {result['next_action']}",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for name, value in result["checks"].items():
        lines.append(f"| `{name}` | `{str(value).lower()}` |")

    lines.extend(["", "## Blockers", ""])
    if result["blockers"]:
        lines.extend(f"- {blocker}" for blocker in result["blockers"])
    else:
        lines.append("- None. Explicit human confirmation is still required before apply.")

    lines.extend(["", "## Warnings", ""])
    if result["warnings"]:
        lines.extend(f"- {warning}" for warning in result["warnings"])
    else:
        lines.append("- None.")

    sandbox_state = result["sandbox"].get("pipeline_state") or {}
    coverage = sandbox_state.get("coverage") or {}
    lines.extend(
        [
            "",
            "## Sandbox Projection",
            "",
            f"- Sandbox stage: `{sandbox_state.get('reviewed_label_stage', 'not_available')}`",
            f"- Projected formal count: {coverage.get('projected_formal_count', 'not_available')}",
            f"- Real official unchanged: `{str(result['sandbox']['real_official_unchanged']).lower()}`",
            "",
            "## Guardrails",
            "",
            "- This preflight is not approval.",
            "- The apply command still requires `--confirm COPY_REVIEWED_LABELS_20260622`.",
            "- Keep automatic tuning disabled until formal gold, official split, and baselines exist.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_preflight_report(
    gold_path: str | Path,
    candidates_path: str | Path,
    preview_path: str | Path,
    official_path: str | Path,
    sandbox_dir: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    result = check_apply_preflight(
        gold_path,
        candidates_path,
        preview_path,
        official_path,
        sandbox_dir,
        **kwargs,
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
    parser.add_argument("--sandbox-dir", default="eval/gold/sandbox/apply_preflight_20260622")
    parser.add_argument("--tune-script", default="scripts/tune_rag_weights.py")
    parser.add_argument("--train-split", default="eval/gold/splits/retrieval_train_20260622.jsonl")
    parser.add_argument("--heldout-split", default="eval/gold/splits/retrieval_heldout_20260622.jsonl")
    parser.add_argument("--condition-evidence-corpus", default="work/econ_rag_experiment/clean_merged_recent_econ.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.json")
    args = parser.parse_args(argv)

    result = write_preflight_report(
        args.gold,
        args.candidates,
        args.preview,
        args.official,
        args.sandbox_dir,
        args.report,
        args.json_report,
        tune_script_path=args.tune_script,
        train_split_path=args.train_split,
        heldout_split_path=args.heldout_split,
        condition_evidence_corpus_path=args.condition_evidence_corpus,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["apply_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
