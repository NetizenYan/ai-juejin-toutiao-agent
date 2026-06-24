"""Check conditional approval rules before reviewed-label promotion.

These checks capture manual-review conditions that are stricter than the base
JSONL shape validator. They keep the official apply step blocked unless the
preview records evidence integrity, answer-boundary policy, and date-window
confirmation clearly enough to review.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


FULL_EVIDENCE_ID_RE = re.compile(r"^news:[a-z]+:[0-9a-f]{16}$")
GROUNDED_INFERENCE_RE = re.compile(r"(帮助|启发|意义|关系|作用|影响)")
INVESTMENT_FORBIDDEN = ["推荐具体股票", "推荐买入卖出", "保证收益", "短线操作建议", "加仓建议"]


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


def _is_accept(row: dict[str, Any]) -> bool:
    return row.get("decision") == "accept_as_gold"


def _texts(row: dict[str, Any]) -> list[str]:
    turns = row.get("turns")
    if isinstance(turns, list):
        return [str(turn) for turn in turns if str(turn).strip()]
    question = row.get("question")
    return [str(question)] if question else []


def _is_grounded_inference_follow_up(row: dict[str, Any]) -> bool:
    if row.get("case_type") != "B_context_follow_up":
        return False
    texts = _texts(row)
    if len(texts) < 2:
        return False
    return bool(GROUNDED_INFERENCE_RE.search(texts[-1]))


def _is_false_premise_follow_up(row: dict[str, Any]) -> bool:
    texts = _texts(row)
    if len(texts) < 2:
        return False
    tail = texts[-1]
    return any(marker in tail for marker in ("是不是", "已经", "说明", "确认"))


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19] if "%H" in fmt else text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _evidence_id_for_row(row: dict[str, Any]) -> str | None:
    evidence_id = row.get("evidence_id")
    if evidence_id:
        return str(evidence_id)
    source = row.get("source")
    source_doc_id = row.get("source_doc_id")
    if source and source_doc_id:
        return f"news:{source}:{source_doc_id}"
    doc_id = str(row.get("doc_id", ""))
    if ":" in doc_id:
        source, _, source_doc_id = doc_id.partition(":")
        if source and source_doc_id:
            return f"news:{source}:{source_doc_id}"
    return None


def _evidence_date_index(evidence_rows: list[dict[str, Any]] | None) -> dict[str, date] | None:
    if evidence_rows is None:
        return None
    index: dict[str, date] = {}
    for row in evidence_rows:
        evidence_id = _evidence_id_for_row(row)
        if not evidence_id:
            continue
        published = (
            _parse_date(row.get("publish_time"))
            or _parse_date(row.get("publish_date"))
            or _parse_date(row.get("date"))
        )
        if published is not None:
            index[evidence_id] = published
    return index


def _time_window(text: str) -> tuple[str, date, date] | None:
    match = re.search(r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<part>上旬|中旬|下旬|初)", text)
    if not match:
        return None
    year = int(match.group("year"))
    month = int(match.group("month"))
    part = match.group("part")
    last_day = calendar.monthrange(year, month)[1]
    if part in {"上旬", "初"}:
        start_day, end_day = 1, 10
    elif part == "中旬":
        start_day, end_day = 11, 20
    else:
        start_day, end_day = 21, last_day
    return f"{year}年{month}月{part}", date(year, month, start_day), date(year, month, end_day)


def _gold_evidence_ids(row: dict[str, Any]) -> list[str]:
    evidence_ids = row.get("gold_evidence_ids")
    if not isinstance(evidence_ids, list):
        return []
    return [str(evidence_id) for evidence_id in evidence_ids]


def _check_e_multi_document(row: dict[str, Any], line_no: int, errors: list[str]) -> None:
    evidence_ids = _gold_evidence_ids(row)
    if len(evidence_ids) < 2:
        errors.append(f"line {line_no}: E_multi_document requires at least two evidence ids")
    bad_ids = [evidence_id for evidence_id in evidence_ids if not FULL_EVIDENCE_ID_RE.match(evidence_id)]
    if bad_ids:
        errors.append(
            f"line {line_no}: E_multi_document requires full evidence ids; invalid={bad_ids}"
        )


def _check_context_follow_up(row: dict[str, Any], line_no: int, errors: list[str]) -> None:
    if not _is_grounded_inference_follow_up(row):
        return
    if row.get("answer_mode") != "context_follow_up_explanation":
        errors.append(
            f"line {line_no}: B_context_follow_up grounded inference requires answer_mode=context_follow_up_explanation"
        )
    if row.get("requires_grounded_inference") is not True:
        errors.append(
            f"line {line_no}: B_context_follow_up grounded inference requires requires_grounded_inference=true"
        )


def _check_no_answer(row: dict[str, Any], line_no: int, errors: list[str]) -> None:
    mode = row.get("no_answer_mode")
    false_follow_up = _is_false_premise_follow_up(row)
    expected_mode = "false_premise_follow_up" if false_follow_up else "unsupported_claim"
    if mode != expected_mode:
        errors.append(f"line {line_no}: G_no_answer requires no_answer_mode={expected_mode}")
    if row.get("should_refuse_false_claim") is not True:
        errors.append(f"line {line_no}: G_no_answer requires should_refuse_false_claim=true")
    if "allowed_fact_summary" not in row:
        errors.append(f"line {line_no}: G_no_answer requires allowed_fact_summary")
    if false_follow_up and row.get("allowed_fact_summary") is not True:
        errors.append(
            f"line {line_no}: G_no_answer false-premise follow-up requires allowed_fact_summary=true"
        )


def _check_investment_boundary(row: dict[str, Any], line_no: int, errors: list[str]) -> None:
    if row.get("should_refuse_investment_advice") is not True:
        errors.append(
            f"line {line_no}: H_investment_boundary requires should_refuse_investment_advice=true"
        )
    if row.get("allowed_fact_summary") is not True:
        errors.append(f"line {line_no}: H_investment_boundary requires allowed_fact_summary=true")
    forbidden = row.get("forbidden")
    if not isinstance(forbidden, list):
        errors.append(f"line {line_no}: H_investment_boundary requires forbidden list")
        return
    missing = [term for term in INVESTMENT_FORBIDDEN if term not in forbidden]
    if missing:
        errors.append(f"line {line_no}: H_investment_boundary forbidden list missing {missing}")


def _check_time_sensitive(
    row: dict[str, Any],
    line_no: int,
    evidence_dates: dict[str, date] | None,
    errors: list[str],
    warnings: list[str],
    date_checks: list[dict[str, Any]],
) -> None:
    window = _time_window(" ".join(_texts(row)))
    if window is None:
        errors.append(f"line {line_no}: C_time_sensitive requires a parsable prompt time window")
        return
    label, start, end = window
    evidence_ids = _gold_evidence_ids(row)
    if evidence_dates is None:
        errors.append(f"line {line_no}: C_time_sensitive requires evidence corpus date confirmation")
        return
    for evidence_id in evidence_ids:
        published = evidence_dates.get(evidence_id)
        if published is None:
            errors.append(f"line {line_no}: C_time_sensitive evidence date missing for {evidence_id}")
            date_checks.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "evidence_id": evidence_id,
                    "window": label,
                    "publish_date": None,
                    "ok": False,
                }
            )
            continue
        ok = start <= published <= end
        date_checks.append(
            {
                "candidate_id": row.get("candidate_id"),
                "evidence_id": evidence_id,
                "window": label,
                "publish_date": published.isoformat(),
                "ok": ok,
            }
        )
        if not ok:
            errors.append(
                f"line {line_no}: C_time_sensitive evidence date outside prompt window "
                f"({evidence_id} {published.isoformat()} not in {label})"
            )
    if not evidence_ids:
        warnings.append(f"line {line_no}: C_time_sensitive has no evidence ids to date-check")


def check_label_conditions(
    label_rows: list[dict[str, Any]],
    *,
    evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    date_checks: list[dict[str, Any]] = []
    checked_counts = {
        "B_context_follow_up": 0,
        "C_time_sensitive": 0,
        "E_multi_document": 0,
        "G_no_answer": 0,
        "H_investment_boundary": 0,
    }
    evidence_dates = _evidence_date_index(evidence_rows)

    for line_no, row in enumerate(label_rows, start=1):
        if not _is_accept(row):
            continue
        case_type = str(row.get("case_type", ""))
        if case_type in checked_counts:
            checked_counts[case_type] += 1
        if case_type == "B_context_follow_up":
            _check_context_follow_up(row, line_no, errors)
        elif case_type == "C_time_sensitive":
            _check_time_sensitive(row, line_no, evidence_dates, errors, warnings, date_checks)
        elif case_type == "E_multi_document":
            _check_e_multi_document(row, line_no, errors)
        elif case_type == "G_no_answer":
            _check_no_answer(row, line_no, errors)
        elif case_type == "H_investment_boundary":
            _check_investment_boundary(row, line_no, errors)

    return {
        "ok": not errors,
        "row_count": len(label_rows),
        "checked_counts": checked_counts,
        "date_checks": date_checks,
        "split_policy": "group_by_evidence_or_parent_news_id",
        "errors": errors,
        "warnings": warnings,
    }


def check_reviewed_label_conditions(
    labels_path: str | Path,
    evidence_corpus_path: str | Path | None = None,
) -> dict[str, Any]:
    evidence_rows = load_jsonl(evidence_corpus_path) if evidence_corpus_path else None
    return check_label_conditions(load_jsonl(labels_path), evidence_rows=evidence_rows)


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Label Conditional Approval",
        "",
        "This report checks the manual-review conditions that must be true before apply.",
        "",
        "## Decision",
        "",
        f"- Conditions ok: `{str(result['ok']).lower()}`",
        f"- Split policy: `{result['split_policy']}`",
        "",
        "## Checked Counts",
        "",
        "| Case type | Accepted rows checked |",
        "| --- | ---: |",
    ]
    for case_type, count in result["checked_counts"].items():
        lines.append(f"| `{case_type}` | {count} |")

    lines.extend(["", "## Errors", ""])
    if result["errors"]:
        lines.extend(f"- {error}" for error in result["errors"])
    else:
        lines.append("- None.")

    lines.extend(["", "## Warnings", ""])
    if result["warnings"]:
        lines.extend(f"- {warning}" for warning in result["warnings"])
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- E multi-document rows must use complete evidence ids.",
            "- C time-sensitive rows must match the evidence publish date window.",
            "- G/H rows must encode refusal boundary and allowed factual summary explicitly.",
            "- Future train/held-out splits must group by evidence id or parent news id.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_condition_report(
    labels_path: str | Path,
    evidence_corpus_path: str | Path | None,
    report_path: str | Path,
    json_report_path: str | Path,
) -> dict[str, Any]:
    result = check_reviewed_label_conditions(labels_path, evidence_corpus_path)
    report = Path(report_path)
    json_report = Path(json_report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    json_report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(result), encoding="utf-8")
    json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default="eval/gold/reviewed_labels_official_preview_20260622.jsonl")
    parser.add_argument("--evidence-corpus", default="work/econ_rag_experiment/clean_merged_recent_econ.jsonl")
    parser.add_argument("--report", default="eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md")
    parser.add_argument("--json-report", default="eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.json")
    args = parser.parse_args(argv)

    result = write_condition_report(args.labels, args.evidence_corpus, args.report, args.json_report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
