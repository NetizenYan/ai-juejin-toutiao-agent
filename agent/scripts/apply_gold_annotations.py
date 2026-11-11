"""Apply relevance annotations (agent/eval/gold/annotations_*.jsonl) to every eval gold file.

Each annotation record carries the final gold_evidence_ids for one case id. Cases flagged
needs_relabel get the annotated ids and lose the flag; other cases keep their human labels
(previous_gold_ids are a subset of the annotated ids by construction). Only changed lines are
rewritten, preserving each file's JSON style. Re-running is a no-op.

Usage (project root):
    .venv/bin/python -m agent.scripts.apply_gold_annotations agent/eval/gold/annotations_claude_20261022.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = PROJECT_ROOT / "agent" / "eval" / "gold"


def load_annotations(path: Path) -> dict[str, dict]:
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["case_id"]] = record
    return records


def apply_to_case(case: dict, record: dict, source_name: str) -> dict:
    previous = case.get("gold_evidence_ids") or []
    missing_human = [ref for ref in previous if ref not in record["gold_evidence_ids"] and not case.get("needs_relabel")]
    if missing_human:
        raise ValueError(f"{case.get('id')}: annotation would drop human gold ids {missing_human}")
    case["gold_evidence_ids"] = list(record["gold_evidence_ids"])
    case.pop("needs_relabel", None)
    case.pop("relabel_reason", None)
    case["gold_annotation"] = source_name
    return case


def apply(annotations: dict[str, dict], source_name: str, gold_dir: Path = GOLD_DIR) -> dict[str, int]:
    stats = {"files_changed": 0, "cases_changed": 0}
    for path in sorted(gold_dir.rglob("*.jsonl")):
        if path.name.startswith("annotations_"):
            continue
        lines, out, changed = path.read_text(encoding="utf-8").splitlines(), [], False
        for line in lines:
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                out.append(line)
                continue
            record = annotations.get(case.get("id")) if isinstance(case, dict) else None
            if record is None or "gold_evidence_ids" not in case:
                out.append(line)
                continue
            before = json.dumps(case, ensure_ascii=False, sort_keys=True)
            case = apply_to_case(case, record, source_name)
            if json.dumps(case, ensure_ascii=False, sort_keys=True) == before:
                out.append(line)
                continue
            changed = True
            stats["cases_changed"] += 1
            compact = '":"' in line or '","' in line
            out.append(json.dumps(case, ensure_ascii=False, separators=(",", ":") if compact else None))
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
            stats["files_changed"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(load_annotations(args.annotations), args.annotations.stem), ensure_ascii=False))


if __name__ == "__main__":
    main()
