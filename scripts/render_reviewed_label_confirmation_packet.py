"""Render a manual confirmation packet for reviewed-label draft decisions.

This tool is read-only. It summarizes draft labels so a reviewer can confirm or
edit them before anything is copied into the official reviewed-label file.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
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


def _display_prompt(row: dict[str, Any]) -> str:
    turns = row.get("turns") or row.get("query_or_turns")
    question = row.get("question")
    if question:
        return str(question)
    if isinstance(turns, list):
        return " / ".join(str(turn) for turn in turns)
    return ""


def _truncate(value: str, limit: int = 90) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", "<br>")


def _decision_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row.get("decision", "")) for row in rows)
    return {decision: counter.get(decision, 0) for decision in DECISIONS}


def _case_type_decision_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts[str(row.get("case_type", "UNKNOWN"))][str(row.get("decision", ""))] += 1
    return {
        case_type: {decision: counter.get(decision, 0) for decision in DECISIONS}
        for case_type, counter in sorted(counts.items())
    }


def build_confirmation_packet(
    candidate_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_by_id = {str(row.get("id", "")): row for row in candidate_rows if row.get("id")}
    output_rows: list[dict[str, Any]] = []

    for idx, label in enumerate(label_rows, start=1):
        candidate_id = str(label.get("candidate_id", ""))
        candidate = candidate_by_id.get(candidate_id, {})
        decision = str(label.get("decision", ""))
        evidence_ids = label.get("gold_evidence_ids") or []
        target_gold_id = label.get("gold_id") or label.get("existing_gold_id") or ""
        prompt = _display_prompt(label) or _display_prompt(candidate)
        output_rows.append(
            {
                "index": idx,
                "candidate_id": candidate_id,
                "decision": decision,
                "case_type": str(label.get("case_type") or candidate.get("case_type") or "UNKNOWN"),
                "target_gold_id": target_gold_id,
                "evidence_count": len(evidence_ids) if isinstance(evidence_ids, list) else 0,
                "prompt_preview": _truncate(prompt),
                "notes": str(label.get("notes", "")),
                "candidate_found": bool(candidate),
                "reviewer_confirmation": "",
            }
        )

    summary = {
        "label_count": len(label_rows),
        "candidate_count": len(candidate_rows),
        "missing_candidate_count": sum(1 for row in output_rows if not row["candidate_found"]),
        "decision_counts": _decision_counts(label_rows),
        "case_type_decision_counts": _case_type_decision_counts(label_rows),
    }
    return {"summary": summary, "rows": output_rows}


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    rows = packet["rows"]
    lines = [
        "# Reviewed Label Confirmation Packet",
        "",
        "This packet turns draft reviewed labels into a reviewer checklist. It is not the official reviewed-label file.",
        "",
        "## Summary",
        "",
        f"- Candidate rows: {summary['candidate_count']}",
        f"- Draft label rows: {summary['label_count']}",
        f"- Missing candidate references: {summary['missing_candidate_count']}",
        f"- Accept as gold: {summary['decision_counts']['accept_as_gold']}",
        f"- Merge with existing: {summary['decision_counts']['merge_with_existing']}",
        f"- Needs evidence lookup: {summary['decision_counts']['needs_evidence_lookup']}",
        f"- Reject: {summary['decision_counts']['reject']}",
        "",
        "## Case Type Counts",
        "",
        "| Case type | Accept | Merge | Lookup | Reject |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for case_type, counts in summary["case_type_decision_counts"].items():
        lines.append(
            "| "
            f"`{case_type}` | "
            f"{counts['accept_as_gold']} | "
            f"{counts['merge_with_existing']} | "
            f"{counts['needs_evidence_lookup']} | "
            f"{counts['reject']} |"
        )

    lines.extend(
        [
            "",
            "## Reviewer Checklist",
            "",
            "| # | Candidate | Decision | Case type | Target gold | Evidence count | Prompt preview | Reviewer confirmation |",
            "| ---: | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"{row['index']} | "
            f"`{_markdown_cell(row['candidate_id'])}` | "
            f"`{_markdown_cell(row['decision'])}` | "
            f"`{_markdown_cell(row['case_type'])}` | "
            f"`{_markdown_cell(row['target_gold_id'])}` | "
            f"{row['evidence_count']} | "
            f"{_markdown_cell(row['prompt_preview'])} | "
            " |"
        )

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not copy this packet into the official reviewed-label file.",
            "- Confirm or edit the draft JSONL rows first, then write confirmed rows to `reviewed_labels_20260622.jsonl`.",
            "- Run reviewed-label validation and promotion audit after official labels are updated.",
            "- Do not create official train/held-out splits or run tuning from this packet.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_confirmation_packet(
    candidates_path: str | Path,
    labels_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
) -> dict[str, Any]:
    packet = build_confirmation_packet(load_jsonl(candidates_path), load_jsonl(labels_path))
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(packet), encoding="utf-8")
    json_report.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--labels", default="eval/gold/reviewed_labels_draft_20260622.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.json")
    args = parser.parse_args(argv)

    packet = write_confirmation_packet(args.candidates, args.labels, args.report, args.json_report)
    print(json.dumps(packet["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
