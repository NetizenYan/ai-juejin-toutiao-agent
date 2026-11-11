"""Remove gold evidence ids listed in a review-decision file from every eval gold file.

The decision file (e.g. agent/eval/gold/blind_review_decisions_20261023.json) maps case id -> ids to
drop. Human-labeled ids never appear there (the decision step keeps them). Only changed lines
are rewritten, preserving each file's JSON style. Re-running is a no-op.

Usage (project root):
    .venv/bin/python -m agent.scripts.apply_gold_removals agent/eval/gold/blind_review_decisions_20261023.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = PROJECT_ROOT / "agent" / "eval" / "gold"


def apply(removals: dict[str, list[str]], source_name: str, gold_dir: Path = GOLD_DIR) -> dict[str, int]:
    stats = {"files_changed": 0, "cases_changed": 0, "ids_removed": 0}
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
            drop = set(removals.get(case.get("id"), [])) if isinstance(case, dict) else set()
            current = case.get("gold_evidence_ids") if isinstance(case, dict) else None
            if not drop or not current or not drop & set(current):
                out.append(line)
                continue
            kept = [ref for ref in current if ref not in drop]
            stats["ids_removed"] += len(current) - len(kept)
            case["gold_evidence_ids"] = kept
            case["gold_review"] = source_name
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
    parser.add_argument("decisions", type=Path)
    args = parser.parse_args()
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    print(json.dumps(apply(decisions["removals"], args.decisions.stem), ensure_ascii=False))


if __name__ == "__main__":
    main()
