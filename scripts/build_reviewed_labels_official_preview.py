"""Build a preview copy of reviewed labels in official-file shape.

This tool is read-only with respect to the real official label file. It creates
a separate preview artifact that can be validated and inspected before a human
decides whether to update `reviewed_labels_20260622.jsonl`.
"""

from __future__ import annotations

import argparse
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


def _decision_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row.get("decision", "")) for row in rows)
    return {decision: counter.get(decision, 0) for decision in DECISIONS}


def build_preview_rows(label_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [dict(row) for row in label_rows]
    summary = {
        "preview_only": True,
        "row_count": len(rows),
        "decision_counts": _decision_counts(rows),
        "accepted_count": sum(1 for row in rows if row.get("decision") == "accept_as_gold"),
        "merge_count": sum(1 for row in rows if row.get("decision") == "merge_with_existing"),
    }
    return rows, summary


def _write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def render_markdown(summary: dict[str, Any], output_path: str | Path) -> str:
    lines = [
        "# Reviewed Labels Official Preview",
        "",
        "## Preview Only",
        "",
        "This file has the same row shape expected by the official reviewed-label file, but it is not official.",
        "",
        "## Summary",
        "",
        f"- Preview output: `{output_path}`",
        f"- Rows: {summary['row_count']}",
        f"- Accept as gold: {summary['decision_counts']['accept_as_gold']}",
        f"- Merge with existing: {summary['decision_counts']['merge_with_existing']}",
        f"- Needs evidence lookup: {summary['decision_counts']['needs_evidence_lookup']}",
        f"- Reject: {summary['decision_counts']['reject']}",
        "",
        "## Guardrails",
        "",
        "- Do not treat this preview as manual confirmation.",
        "- Do not overwrite `eval/gold/reviewed_labels_20260622.jsonl` without reviewer approval.",
        "- Validate this preview before any manual promotion step.",
        "- Keep automatic tuning closed until the official split and baselines exist.",
    ]
    return "\n".join(lines) + "\n"


def write_official_preview(
    draft_labels_path: str | Path,
    output_path: str | Path,
    summary_path: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    rows, summary = build_preview_rows(load_jsonl(draft_labels_path))
    summary = {
        **summary,
        "source_path": str(draft_labels_path),
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
    }
    _write_jsonl(output_path, rows)
    summary_output = Path(summary_path)
    report_output = Path(report_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_output.write_text(render_markdown(summary, output_path), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft-labels", default="eval/gold/reviewed_labels_draft_20260622.jsonl")
    parser.add_argument("--output", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--summary", default="eval/gold/reviewed_labels_official_preview_20260622.json")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABELS_OFFICIAL_PREVIEW_20260622.md")
    args = parser.parse_args(argv)

    summary = write_official_preview(args.draft_labels, args.output, args.summary, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
