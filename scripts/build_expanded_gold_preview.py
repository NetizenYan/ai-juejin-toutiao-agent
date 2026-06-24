"""Build a preview expanded retrieval gold set from reviewed labels.

This tool writes a separate preview file. It never modifies the formal gold
file in place.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


GOLD_FIELDS = (
    "id",
    "expected_route",
    "gold_evidence_ids",
    "should_answer",
    "should_refuse",
    "must_have_citations",
    "case_type",
    "notes",
)

OPTIONAL_GOLD_FIELDS = (
    "answer_mode",
    "requires_grounded_inference",
    "no_answer_mode",
    "should_refuse_false_claim",
    "allowed_fact_summary",
    "should_refuse_investment_advice",
    "forbidden",
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


def _label_to_gold_row(label: dict[str, Any]) -> dict[str, Any]:
    row = {"id": label["gold_id"]}
    question = label.get("question")
    turns = label.get("turns")
    if question:
        row["question"] = question
    elif turns:
        row["turns"] = turns
    else:
        raise ValueError(f"{label.get('candidate_id')}: accept_as_gold requires question or turns")

    for field in GOLD_FIELDS:
        if field == "id":
            continue
        row[field] = label[field]
    for field in OPTIONAL_GOLD_FIELDS:
        if field in label:
            row[field] = label[field]
    return row


def build_expanded_gold_rows(
    gold_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expanded = [dict(row) for row in gold_rows]
    seen_ids = {str(row.get("id", "")) for row in expanded if row.get("id")}
    if len(seen_ids) != len(expanded):
        raise ValueError("formal gold contains duplicate or missing ids")

    accepted_added = 0
    merge_skipped = 0
    rejected_skipped = 0
    lookup_skipped = 0
    accepted_counts: Counter[str] = Counter()

    for label in label_rows:
        decision = label.get("decision")
        if decision == "accept_as_gold":
            gold_id = str(label.get("gold_id", ""))
            if not gold_id:
                raise ValueError(f"{label.get('candidate_id')}: accept_as_gold requires gold_id")
            if gold_id in seen_ids:
                raise ValueError(f"duplicate gold id {gold_id}")
            row = _label_to_gold_row(label)
            expanded.append(row)
            seen_ids.add(gold_id)
            accepted_added += 1
            accepted_counts[str(row.get("case_type", "UNKNOWN"))] += 1
        elif decision == "merge_with_existing":
            merge_skipped += 1
        elif decision == "reject":
            rejected_skipped += 1
        elif decision == "needs_evidence_lookup":
            lookup_skipped += 1

    summary = {
        "base_count": len(gold_rows),
        "accepted_added": accepted_added,
        "merge_skipped": merge_skipped,
        "rejected_skipped": rejected_skipped,
        "needs_lookup_skipped": lookup_skipped,
        "projected_count": len(expanded),
        "accepted_counts": dict(sorted(accepted_counts.items())),
    }
    return expanded, summary


def write_expanded_gold_preview(
    gold_path: str | Path,
    labels_path: str | Path,
    output_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any]:
    expanded, summary = build_expanded_gold_rows(load_jsonl(gold_path), load_jsonl(labels_path))
    Path(output_path).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in expanded) + ("\n" if expanded else ""),
        encoding="utf-8",
    )
    Path(summary_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval.jsonl")
    parser.add_argument("--labels", default="eval/gold/reviewed_labels_20260622.jsonl")
    parser.add_argument("--output", default="eval/gold/eval_gold_retrieval_expanded_preview_20260622.jsonl")
    parser.add_argument("--summary", default="eval/gold/eval_gold_retrieval_expanded_preview_20260622.json")
    args = parser.parse_args(argv)

    summary = write_expanded_gold_preview(args.gold, args.labels, args.output, args.summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
