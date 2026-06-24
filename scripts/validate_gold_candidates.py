"""Validate the 3.3 retrieval gold candidate queue."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ALLOWED_CASE_TYPES = {
    "A_exact_news_qa",
    "B_context_follow_up",
    "C_time_sensitive",
    "D_source_limited",
    "E_multi_document",
    "F_similar_distractor",
    "G_no_answer",
    "H_investment_boundary",
}

ALLOWED_STATUSES = {
    "needs_label_review",
    "needs_evidence_lookup",
    "reviewed",
    "rejected",
}

REQUIRED_FIELDS = {
    "id",
    "source",
    "case_type",
    "query_or_turns",
    "reason",
    "status",
}


@dataclass
class CandidateValidationResult:
    ok: bool
    row_count: int
    errors: list[str]


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], [f"{path}: file does not exist"]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_no}: row must be a JSON object")
            continue
        rows.append(value)
    return rows, errors


def _valid_query_or_turns(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def validate_candidates(path: str | Path) -> CandidateValidationResult:
    rows, errors = _load_jsonl(Path(path))
    seen_ids: set[str] = set()

    for idx, row in enumerate(rows, start=1):
        missing = sorted(field for field in REQUIRED_FIELDS if field not in row)
        for field in missing:
            errors.append(f"line {idx}: {field} is required")

        candidate_id = row.get("id")
        if isinstance(candidate_id, str) and candidate_id.strip():
            if candidate_id in seen_ids:
                errors.append(f"line {idx}: duplicate id {candidate_id}")
            seen_ids.add(candidate_id)
        else:
            errors.append(f"line {idx}: id must be a non-empty string")

        source = row.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"line {idx}: source is required")

        case_type = row.get("case_type")
        if case_type not in ALLOWED_CASE_TYPES:
            errors.append(f"line {idx}: invalid case_type {case_type!r}")

        if not _valid_query_or_turns(row.get("query_or_turns")):
            errors.append(f"line {idx}: query_or_turns must be a non-empty list of non-empty strings")

        reason = row.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"line {idx}: reason is required")

        status = row.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"line {idx}: invalid status {status!r}")

    return CandidateValidationResult(ok=not errors, row_count=len(rows), errors=errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    args = parser.parse_args(argv)

    result = validate_candidates(args.candidates)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
