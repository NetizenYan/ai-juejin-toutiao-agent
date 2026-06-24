"""Audit retrieval-gold candidate text readability.

This is a read-only UTF-8/content sanity check for manual review artifacts.
It does not modify candidates, labels, formal gold, or split files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MOJIBAKE_MARKERS = (
    "缁忔祹",
    "鏃ユ姤",
    "鏂伴椈",
    "浠€涔",
    "浜у姏",
    "楂樿川",
    "鍙戝睍",
    "锛",
    "紵",
    "€",
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


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or row.get("id") or row.get("gold_id") or "UNKNOWN")


def _prompt_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("question", "query_or_turns", "turns"):
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item is not None)
        elif value:
            parts.append(str(value))
    return " ".join(parts).strip()


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _mojibake_marker_count(text: str) -> int:
    return sum(1 for marker in MOJIBAKE_MARKERS if marker in text)


def summarize_readability(
    rows: list[dict[str, Any]],
    *,
    fallback_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fallback_by_id = {
        str(row.get("id") or row.get("candidate_id") or ""): row
        for row in (fallback_rows or [])
        if row.get("id") or row.get("candidate_id")
    }
    problem_rows: list[dict[str, Any]] = []
    rows_with_text = 0
    rows_with_cjk = 0
    rows_without_text = 0
    rows_without_cjk = 0
    replacement_char_rows = 0
    ascii_question_mark_rows = 0
    mojibake_suspect_rows = 0

    for row in rows:
        row_id = _row_id(row)
        text = _prompt_text(row)
        if not text and row_id in fallback_by_id:
            text = _prompt_text(fallback_by_id[row_id])
        problems: list[str] = []
        if not text:
            rows_without_text += 1
            problems.append("missing prompt text")
        else:
            rows_with_text += 1
            if _has_cjk(text):
                rows_with_cjk += 1
            else:
                rows_without_cjk += 1
                problems.append("prompt has no CJK characters")
            if "\ufffd" in text:
                replacement_char_rows += 1
                problems.append("prompt contains Unicode replacement character")
            if "?" in text:
                ascii_question_mark_rows += 1
                problems.append("prompt contains ASCII question mark")
            if _mojibake_marker_count(text) >= 2:
                mojibake_suspect_rows += 1
                problems.append("prompt has mojibake-like marker patterns")

        if problems:
            problem_rows.append(
                {
                    "row_id": row_id,
                    "case_type": str(row.get("case_type", "UNKNOWN")),
                    "problems": problems,
                    "prompt_preview": text[:120],
                }
            )

    blocking_problem_count = (
        rows_without_text
        + rows_without_cjk
        + replacement_char_rows
        + mojibake_suspect_rows
    )
    return {
        "ok": blocking_problem_count == 0,
        "row_count": len(rows),
        "fallback_row_count": len(fallback_by_id),
        "rows_with_text": rows_with_text,
        "rows_with_cjk": rows_with_cjk,
        "rows_without_text": rows_without_text,
        "rows_without_cjk": rows_without_cjk,
        "replacement_char_rows": replacement_char_rows,
        "ascii_question_mark_rows": ascii_question_mark_rows,
        "mojibake_suspect_rows": mojibake_suspect_rows,
        "problem_rows": problem_rows,
    }


def render_markdown(summary: dict[str, Any], source_path: str | Path) -> str:
    lines = [
        "# Gold Text Readability Audit",
        "",
        "This report checks prompt text readability for manual review files. It is read-only.",
        "",
        "## Summary",
        "",
        f"- Source: `{source_path}`",
        f"- OK: `{str(summary['ok']).lower()}`",
        f"- Rows: {summary['row_count']}",
        f"- Fallback rows: {summary['fallback_row_count']}",
        f"- Rows with prompt text: {summary['rows_with_text']}",
        f"- Rows with CJK text: {summary['rows_with_cjk']}",
        f"- Rows missing prompt text: {summary['rows_without_text']}",
        f"- Rows without CJK text: {summary['rows_without_cjk']}",
        f"- Rows with Unicode replacement characters: {summary['replacement_char_rows']}",
        f"- Rows with ASCII question marks: {summary['ascii_question_mark_rows']}",
        f"- Rows with mojibake marker patterns: {summary['mojibake_suspect_rows']}",
        "",
        "## Problem Rows",
        "",
    ]
    if summary["problem_rows"]:
        lines.extend(
            [
                "| Row id | Case type | Problems | Prompt preview |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in summary["problem_rows"]:
            problems = ", ".join(row["problems"])
            preview = str(row["prompt_preview"]).replace("|", "\\|").replace("\n", " ")
            lines.append(
                "| "
                f"`{row['row_id']}` | "
                f"`{row['case_type']}` | "
                f"{problems} | "
                f"{preview} |"
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- If PowerShell displays Chinese as mojibake, inspect the Markdown or JSONL file in a UTF-8 aware editor.",
            "- This audit checks stored file content, not terminal rendering.",
            "- Do not use this report to promote labels without manual review.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_readability_audit(
    source_path: str | Path,
    report_path: str | Path,
    json_report_path: str | Path,
    *,
    fallback_source_path: str | Path | None = None,
) -> dict[str, Any]:
    summary = summarize_readability(
        load_jsonl(source_path),
        fallback_rows=load_jsonl(fallback_source_path) if fallback_source_path else None,
    )
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(summary, source_path), encoding="utf-8")
    json_report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="eval/gold/reviewed_labels_draft_20260622.jsonl")
    parser.add_argument("--fallback-source", default="")
    parser.add_argument("--report", default="eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.json")
    args = parser.parse_args(argv)

    summary = write_readability_audit(
        args.source,
        args.report,
        args.json_report,
        fallback_source_path=args.fallback_source or None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
