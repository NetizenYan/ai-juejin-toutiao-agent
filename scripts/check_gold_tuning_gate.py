"""Check whether 3.3 automatic retrieval-weight tuning is allowed."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MIN_FORMAL_GOLD = 100
MIN_HELDOUT = 30
MIN_MAJOR_CLASS_COUNT = 10
MAJOR_CASE_TYPES = (
    "A_exact_news_qa",
    "B_context_follow_up",
    "C_time_sensitive",
    "D_source_limited",
    "E_multi_document",
    "F_similar_distractor",
    "G_no_answer",
    "H_investment_boundary",
)


@dataclass
class TuningGateResult:
    ok: bool
    formal_count: int
    train_count: int
    heldout_count: int
    blockers: list[str]


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _count_jsonl(path: str | Path | None) -> int | None:
    if path is None:
        return None
    jsonl_path = Path(path)
    if not jsonl_path.exists():
        return None
    return sum(1 for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip())


def _exists(path: str | Path | None) -> bool:
    return bool(path) and Path(path).exists()


def check_tuning_gate(
    coverage: dict[str, Any],
    *,
    train_split_path: str | Path | None = None,
    heldout_split_path: str | Path | None = None,
    train_report_path: str | Path | None = None,
    heldout_report_path: str | Path | None = None,
) -> TuningGateResult:
    blockers: list[str] = []
    formal_count = int(coverage.get("formal_count", 0))
    formal_counts = coverage.get("formal_counts") or {}

    if formal_count < MIN_FORMAL_GOLD:
        blockers.append(f"formal gold count {formal_count} is below {MIN_FORMAL_GOLD}")

    for case_type in MAJOR_CASE_TYPES:
        count = int(formal_counts.get(case_type, 0))
        if count < MIN_MAJOR_CLASS_COUNT:
            blockers.append(
                f"{case_type} has {count} formal cases, below {MIN_MAJOR_CLASS_COUNT}"
            )

    train_count = _count_jsonl(train_split_path)
    heldout_count = _count_jsonl(heldout_split_path)
    if train_count is None:
        blockers.append("train split is missing")
        train_count = 0
    if heldout_count is None:
        blockers.append("held-out split is missing")
        heldout_count = 0
    elif heldout_count < MIN_HELDOUT:
        blockers.append(f"held-out split has {heldout_count} cases, below {MIN_HELDOUT}")

    if not _exists(train_report_path):
        blockers.append("train baseline report is missing")
    if not _exists(heldout_report_path):
        blockers.append("held-out baseline report is missing")

    return TuningGateResult(
        ok=not blockers,
        formal_count=formal_count,
        train_count=train_count,
        heldout_count=heldout_count,
        blockers=blockers,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", default="eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json")
    parser.add_argument("--train-split", default="eval/gold/splits/retrieval_train_202606.jsonl")
    parser.add_argument("--heldout-split", default="eval/gold/splits/retrieval_heldout_202606.jsonl")
    parser.add_argument("--train-report", default="eval/reports/3_3/train_baseline_3_2E.json")
    parser.add_argument("--heldout-report", default="eval/reports/3_3/heldout_baseline_3_2E.json")
    args = parser.parse_args(argv)

    result = check_tuning_gate(
        _load_json(args.coverage),
        train_split_path=args.train_split,
        heldout_split_path=args.heldout_split,
        train_report_path=args.train_report,
        heldout_report_path=args.heldout_report,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
