"""Validate reviewed retrieval-gold candidate labels."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ALLOWED_DECISIONS = {
    "accept_as_gold",
    "merge_with_existing",
    "needs_evidence_lookup",
    "reject",
}

ACCEPT_REQUIRED_FIELDS = {
    "candidate_id",
    "decision",
    "gold_id",
    "expected_route",
    "gold_evidence_ids",
    "should_answer",
    "should_refuse",
    "must_have_citations",
    "case_type",
    "notes",
}


@dataclass
class ValidationResult:
    ok: bool
    row_count: int
    accepted_count: int
    rejected_count: int
    errors: list[str]


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, [f"{path}: file does not exist"]

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


def validate_reviewed_labels(candidates_path: str | Path, labels_path: str | Path) -> ValidationResult:
    candidates, candidate_errors = _load_jsonl(Path(candidates_path))
    labels, label_errors = _load_jsonl(Path(labels_path))
    errors = [*candidate_errors, *label_errors]

    candidate_ids = {str(row.get("id", "")) for row in candidates if row.get("id")}
    seen_candidate_ids: set[str] = set()
    seen_gold_ids: set[str] = set()
    accepted_count = 0
    rejected_count = 0

    for idx, row in enumerate(labels, start=1):
        candidate_id = str(row.get("candidate_id", ""))
        decision = row.get("decision")

        if not candidate_id:
            errors.append(f"line {idx}: candidate_id is required")
        elif candidate_id not in candidate_ids:
            errors.append(f"line {idx}: unknown candidate_id {candidate_id}")
        elif candidate_id in seen_candidate_ids:
            errors.append(f"line {idx}: duplicate candidate_id {candidate_id}")
        seen_candidate_ids.add(candidate_id)

        if decision not in ALLOWED_DECISIONS:
            errors.append(f"line {idx}: invalid decision {decision!r}")
            continue

        if decision == "accept_as_gold":
            accepted_count += 1
            missing = sorted(field for field in ACCEPT_REQUIRED_FIELDS if field not in row)
            for field in missing:
                errors.append(f"line {idx}: accept_as_gold requires {field}")

            if not row.get("question") and not row.get("turns"):
                errors.append(f"line {idx}: accept_as_gold requires question or turns")
            evidence_ids = row.get("gold_evidence_ids")
            if not isinstance(evidence_ids, list):
                errors.append(f"line {idx}: accept_as_gold requires gold_evidence_ids to be a list")
            elif row.get("should_answer") and row.get("must_have_citations") and not evidence_ids:
                errors.append(f"line {idx}: answerable accept_as_gold requires non-empty gold_evidence_ids")
            gold_id = str(row.get("gold_id", ""))
            if gold_id:
                if gold_id in seen_gold_ids:
                    errors.append(f"line {idx}: duplicate gold_id {gold_id}")
                seen_gold_ids.add(gold_id)
        elif decision == "reject":
            rejected_count += 1
            if not row.get("notes"):
                errors.append(f"line {idx}: reject requires notes")
        else:
            if not row.get("notes"):
                errors.append(f"line {idx}: {decision} requires notes")

    return ValidationResult(
        ok=not errors,
        row_count=len(labels),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="eval/gold/gray_candidates_20260622.jsonl")
    parser.add_argument("--labels", default="eval/gold/reviewed_labels_20260622.jsonl")
    args = parser.parse_args(argv)

    result = validate_reviewed_labels(args.candidates, args.labels)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
