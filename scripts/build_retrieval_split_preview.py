"""Build a deterministic train/held-out preview split for retrieval gold.

This tool is intentionally preview-only. It does not create the official
3.3 split files used by the automatic tuning gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HELDOUT_RATIO = 0.3
DEFAULT_MIN_HELDOUT = 30
DEFAULT_SEED = "20260622"


@dataclass
class SplitPreview:
    train_rows: list[dict[str, Any]]
    heldout_rows: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass
class EvidenceGroup:
    key: str
    rows: list[dict[str, Any]]


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


def _write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _validate_ids(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for row in rows:
        gold_id = str(row.get("id", "")).strip()
        if not gold_id:
            raise ValueError("missing gold id")
        if gold_id in seen:
            raise ValueError(f"duplicate gold id {gold_id}")
        seen.add(gold_id)


def _heldout_target(total: int, heldout_ratio: float, min_heldout: int) -> int:
    if total <= 1:
        return 0
    ratio_target = math.ceil(total * heldout_ratio)
    target = max(ratio_target, min_heldout) if total >= min_heldout else ratio_target
    return min(target, total - 1)


def _stable_sort_key(row: dict[str, Any], seed: str) -> str:
    gold_id = str(row["id"])
    return hashlib.sha256(f"{seed}:{gold_id}".encode("utf-8")).hexdigest()


def _stable_value_key(value: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def _row_evidence_tokens(row: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    evidence_ids = row.get("gold_evidence_ids")
    if isinstance(evidence_ids, list):
        tokens.extend(f"evidence:{evidence_id}" for evidence_id in evidence_ids if str(evidence_id).strip())

    parent_news_ids = row.get("parent_news_ids")
    if isinstance(parent_news_ids, list):
        tokens.extend(f"parent:{parent_id}" for parent_id in parent_news_ids if str(parent_id).strip())
    parent_news_id = row.get("parent_news_id")
    if parent_news_id:
        tokens.append(f"parent:{parent_news_id}")

    if not tokens:
        tokens.append(f"row:{row['id']}")
    return sorted(set(str(token) for token in tokens))


def _evidence_groups(rows: list[dict[str, Any]]) -> list[EvidenceGroup]:
    parent: dict[str, str] = {}
    token_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def find(token: str) -> str:
        parent.setdefault(token, token)
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for row in rows:
        tokens = _row_evidence_tokens(row)
        for token in tokens:
            find(token)
            token_rows[token].append(row)
        first = tokens[0]
        for token in tokens[1:]:
            union(first, token)

    grouped_tokens: dict[str, set[str]] = defaultdict(set)
    for token in token_rows:
        grouped_tokens[find(token)].add(token)

    groups: list[EvidenceGroup] = []
    seen_row_ids_by_group: dict[str, set[str]] = defaultdict(set)
    rows_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for token, rows_for_token in token_rows.items():
        root = find(token)
        for row in rows_for_token:
            row_id = str(row["id"])
            if row_id in seen_row_ids_by_group[root]:
                continue
            seen_row_ids_by_group[root].add(row_id)
            rows_by_group[root].append(row)

    for root, group_rows in rows_by_group.items():
        key = sorted(grouped_tokens[root])[0]
        groups.append(EvidenceGroup(key=key, rows=group_rows))
    return groups


def _primary_case_type(group: EvidenceGroup) -> str:
    counts = _class_counts(group.rows)
    return sorted(counts, key=lambda case_type: (-counts[case_type], case_type))[0]


def _select_heldout_groups(
    evidence_groups: list[EvidenceGroup],
    desired_counts: dict[str, int],
    heldout_target: int,
    seed: str,
) -> set[str]:
    remaining = list(evidence_groups)
    selected_keys: set[str] = set()
    heldout_counts: Counter[str] = Counter()
    heldout_total = 0

    def add_group(group: EvidenceGroup) -> None:
        nonlocal heldout_total
        selected_keys.add(group.key)
        heldout_total += len(group.rows)
        heldout_counts.update(_class_counts(group.rows))
        remaining.remove(group)

    while remaining and heldout_total < heldout_target:
        fitting = [group for group in remaining if heldout_total + len(group.rows) <= heldout_target]
        if not fitting:
            break

        def score(group: EvidenceGroup) -> tuple[float, int, str]:
            case_counts = _class_counts(group.rows)
            deficit_gain = sum(
                min(count, max(0, desired_counts.get(case_type, 0) - heldout_counts.get(case_type, 0)))
                for case_type, count in case_counts.items()
            )
            if deficit_gain == 0:
                deficit_gain = 0.01
            return (-deficit_gain, len(group.rows), _stable_value_key(group.key, seed))

        add_group(sorted(fitting, key=score)[0])

    if remaining and heldout_total < heldout_target:
        current_gap = abs(heldout_target - heldout_total)
        overshoot = sorted(
            remaining,
            key=lambda group: (
                abs(heldout_target - (heldout_total + len(group.rows))),
                len(group.rows),
                _stable_value_key(group.key, seed),
            ),
        )[0]
        next_gap = abs(heldout_target - (heldout_total + len(overshoot.rows)))
        if next_gap < current_gap:
            add_group(overshoot)

    return selected_keys


def _allocate_heldout_counts(
    groups: dict[str, list[dict[str, Any]]],
    heldout_target: int,
) -> dict[str, int]:
    if heldout_target <= 0:
        return {case_type: 0 for case_type in groups}

    total = sum(len(rows) for rows in groups.values())
    allocations: dict[str, int] = {}
    capacities: dict[str, int] = {}
    fractions: dict[str, float] = {}

    for case_type, rows in groups.items():
        capacity = max(0, len(rows) - 1)
        raw_quota = len(rows) * heldout_target / total
        base = min(math.floor(raw_quota), capacity)
        allocations[case_type] = base
        capacities[case_type] = capacity
        fractions[case_type] = raw_quota - math.floor(raw_quota)

    remaining = heldout_target - sum(allocations.values())
    priority = sorted(
        groups,
        key=lambda case_type: (
            -fractions[case_type],
            -len(groups[case_type]),
            case_type,
        ),
    )

    while remaining > 0:
        progressed = False
        for case_type in priority:
            if allocations[case_type] >= capacities[case_type]:
                continue
            allocations[case_type] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            break

    return allocations


def _class_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("case_type", "UNKNOWN")) for row in rows)


def _summary(
    rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
    heldout_rows: list[dict[str, Any]],
    *,
    heldout_ratio: float,
    min_heldout: int,
    seed: str,
    train_path: str | None = None,
    heldout_path: str | None = None,
    summary_path: str | None = None,
    report_path: str | None = None,
) -> dict[str, Any]:
    total_counts = _class_counts(rows)
    train_counts = _class_counts(train_rows)
    heldout_counts = _class_counts(heldout_rows)
    case_types = sorted(total_counts)
    train_ids = {str(row["id"]) for row in train_rows}
    heldout_ids = {str(row["id"]) for row in heldout_rows}
    train_tokens = {token for row in train_rows for token in _row_evidence_tokens(row)}
    heldout_tokens = {token for row in heldout_rows for token in _row_evidence_tokens(row)}

    return {
        "preview_only": True,
        "input_count": len(rows),
        "train_count": len(train_rows),
        "heldout_count": len(heldout_rows),
        "evidence_group_count": len(_evidence_groups(rows)),
        "evidence_group_overlap_count": len(train_tokens & heldout_tokens),
        "heldout_ratio": heldout_ratio,
        "min_heldout": min_heldout,
        "seed": seed,
        "train_path": train_path,
        "heldout_path": heldout_path,
        "summary_path": summary_path,
        "report_path": report_path,
        "overlap_count": len(train_ids & heldout_ids),
        "unique_id_count": len(train_ids | heldout_ids),
        "class_counts": {
            case_type: {
                "total": total_counts.get(case_type, 0),
                "train": train_counts.get(case_type, 0),
                "heldout": heldout_counts.get(case_type, 0),
            }
            for case_type in case_types
        },
    }


def build_split_preview(
    rows: list[dict[str, Any]],
    *,
    heldout_ratio: float = DEFAULT_HELDOUT_RATIO,
    min_heldout: int = DEFAULT_MIN_HELDOUT,
    seed: str = DEFAULT_SEED,
) -> SplitPreview:
    _validate_ids(rows)
    evidence_groups = _evidence_groups(rows)
    row_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_groups[str(row.get("case_type", "UNKNOWN"))].append(row)

    heldout_target = _heldout_target(len(rows), heldout_ratio, min_heldout)
    allocations = _allocate_heldout_counts(row_groups, heldout_target)
    selected_group_keys = _select_heldout_groups(evidence_groups, allocations, heldout_target, seed)
    heldout_ids = {
        str(row["id"])
        for group in evidence_groups
        if group.key in selected_group_keys
        for row in group.rows
    }

    train_rows = [dict(row) for row in rows if str(row["id"]) not in heldout_ids]
    heldout_rows = [dict(row) for row in rows if str(row["id"]) in heldout_ids]
    summary = _summary(
        rows,
        train_rows,
        heldout_rows,
        heldout_ratio=heldout_ratio,
        min_heldout=min_heldout,
        seed=seed,
    )
    return SplitPreview(train_rows=train_rows, heldout_rows=heldout_rows, summary=summary)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Retrieval Split Preview",
        "",
        "## Preview Only",
        "",
        "This split is generated from a preview gold file. It must not be used as the official tuning split.",
        "",
        "## Summary",
        "",
        f"- Input cases: {summary['input_count']}",
        f"- Train cases: {summary['train_count']}",
        f"- Held-out cases: {summary['heldout_count']}",
        f"- Held-out ratio: {summary['heldout_ratio']}",
        f"- Minimum held-out target: {summary['min_heldout']}",
        f"- Seed: `{summary['seed']}`",
        f"- Overlap count: {summary['overlap_count']}",
        f"- Evidence groups: {summary['evidence_group_count']}",
        f"- Evidence group overlap: {summary['evidence_group_overlap_count']}",
        "",
        "## Class Counts",
        "",
        "| Case type | Total | Train | Held-out |",
        "| --- | ---: | ---: | ---: |",
    ]
    for case_type, counts in summary["class_counts"].items():
        lines.append(
            "| "
            f"`{case_type}` | "
            f"{counts['total']} | "
            f"{counts['train']} | "
            f"{counts['heldout']} |"
        )

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not use this preview split for automatic tuning decisions.",
            "- Do not create official split files until reviewed labels are confirmed.",
            "- Keep the tuning gate closed until train and held-out 3.2E baselines exist.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_split_preview(
    gold_path: str | Path,
    train_output_path: str | Path,
    heldout_output_path: str | Path,
    summary_output_path: str | Path,
    report_output_path: str | Path,
    *,
    heldout_ratio: float = DEFAULT_HELDOUT_RATIO,
    min_heldout: int = DEFAULT_MIN_HELDOUT,
    seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    split = build_split_preview(
        load_jsonl(gold_path),
        heldout_ratio=heldout_ratio,
        min_heldout=min_heldout,
        seed=seed,
    )
    summary = _summary(
        load_jsonl(gold_path),
        split.train_rows,
        split.heldout_rows,
        heldout_ratio=heldout_ratio,
        min_heldout=min_heldout,
        seed=seed,
        train_path=str(train_output_path),
        heldout_path=str(heldout_output_path),
        summary_path=str(summary_output_path),
        report_path=str(report_output_path),
    )

    _write_jsonl(train_output_path, split.train_rows)
    _write_jsonl(heldout_output_path, split.heldout_rows)
    summary_path = Path(summary_output_path)
    report_path = Path(report_output_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_markdown(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/gold/eval_gold_retrieval_draft_expanded_preview_20260622.jsonl")
    parser.add_argument("--train-output", default="eval/gold/splits/preview/retrieval_train_preview_20260622.jsonl")
    parser.add_argument("--heldout-output", default="eval/gold/splits/preview/retrieval_heldout_preview_20260622.jsonl")
    parser.add_argument("--summary", default="eval/gold/splits/preview/retrieval_split_preview_20260622.json")
    parser.add_argument("--report", default="eval/gold/splits/preview/RETRIEVAL_SPLIT_PREVIEW_20260622.md")
    parser.add_argument("--heldout-ratio", type=float, default=DEFAULT_HELDOUT_RATIO)
    parser.add_argument("--min-heldout", type=int, default=DEFAULT_MIN_HELDOUT)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    summary = write_split_preview(
        args.gold,
        args.train_output,
        args.heldout_output,
        args.summary,
        args.report,
        heldout_ratio=args.heldout_ratio,
        min_heldout=args.min_heldout,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
