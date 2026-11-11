"""Migrate agent/eval/gold evidence ids from the June 2026 corpus to the rebuilt corpus.

The June ids (news:jjrb:<hash>) came from an uncommitted cleaning step and cannot be reproduced from
the raw data. An old id is mapped only when one of the gold questions that cite it names an article
title from the rebuilt corpus (backend/scripts/build_econ_corpus.py) verbatim, allowing one missing character.
Same-titled columns published on several dates map to all of them. Everything else stays unmapped:
its id is dropped from gold_evidence_ids, and a case left without ids gets needs_relabel=true
(eval_context_rag skips cases without gold ids when computing recall).

Usage (project root):
    .venv/bin/python -m agent.scripts.migrate_gold_evidence_ids \
        --corpus backend/data/processed/econ_corpus_20250610_20260610.jsonl --apply
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = PROJECT_ROOT / "agent" / "eval" / "gold"
DEFAULT_MAPPING = GOLD_DIR / "evidence_id_migration_20261022.json"
ID_RE = re.compile(r"news:(?:jjrb|rmrb):[0-9a-f]{16}")
_PUNCT_RE = re.compile(r"[\s，。！？、“”‘’《》：:（）()·\-—…\"']")
MIN_TITLE_CHARS = 5


def normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text or "")


def _lcs(a: str, b: str) -> int:
    best, prev = 0, [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            value = prev[j - 1] + 1 if ca == cb else 0
            cur.append(value)
            best = max(best, value)
        prev = cur
    return best


def title_named(title: str, question: str) -> bool:
    """True when the question contains the title, allowing one missing character (e.g. a leading 在)."""
    if title in question:
        return True
    return len(title) >= MIN_TITLE_CHARS + 1 and _lcs(question, title) >= len(title) - 1


def gold_files(gold_dir: Path) -> list[Path]:
    return sorted(gold_dir.rglob("*.jsonl"))


def questions_by_id(files: list[Path]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue
            texts = [case.get("question") or ""]
            texts += [t for t in (case.get("query_or_turns") or case.get("turns") or []) if isinstance(t, str)]
            for old_id in set(ID_RE.findall(line)):
                found[old_id].update(normalize(t) for t in texts if t)
    return found


def build_mapping(corpus: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    titles: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    current_ids: set[str] = set()
    with corpus.open(encoding="utf-8") as handle:
        for line in handle:
            doc = json.loads(line)
            current_ids.add(doc["evidence_id"])
            key = normalize(doc["title"])
            if len(key) >= MIN_TITLE_CHARS:
                titles[(doc["source"], key)].append(doc)

    mapping: dict[str, dict[str, Any]] = {}
    for old_id, questions in sorted(questions_by_id(files).items()):
        if old_id in current_ids:  # already migrated: re-running must not drop it
            mapping[old_id] = {"status": "mapped", "new_ids": [old_id], "title": "", "publish_dates": []}
            continue
        source = old_id.split(":")[1]
        named = {key: docs for (src, key), docs in titles.items()
                 if src == source and any(title_named(key, q) for q in questions)}
        # "推进内外贸一体化" is inside "推进内外贸一体化用好两个市场…": keep the most specific title.
        named = {k: v for k, v in named.items() if not any(k != other and k in other for other in named)}
        if len(named) == 1:
            docs = next(iter(named.values()))
            mapping[old_id] = {
                "status": "mapped",
                "new_ids": [d["evidence_id"] for d in docs],
                "title": docs[0]["title"],
                "publish_dates": [d["publish_time"][:10] for d in docs],
            }
        else:
            mapping[old_id] = {
                "status": "unmapped",
                "reason": "questions name several different titles" if named else "no question names a title",
                "candidate_titles": sorted(docs[0]["title"] for docs in named.values()),
            }
    return mapping


def migrate_case(case: dict[str, Any], mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    old_ids = case.get("gold_evidence_ids")
    if isinstance(old_ids, list) and any(ID_RE.fullmatch(str(i)) for i in old_ids):
        new_ids: list[str] = []
        for old in old_ids:
            entry = mapping.get(str(old))
            replacement = entry["new_ids"] if entry and entry["status"] == "mapped" else []
            if not ID_RE.fullmatch(str(old)):
                replacement = [old]
            for new in replacement:
                if new not in new_ids:
                    new_ids.append(new)
        case["gold_evidence_ids"] = new_ids
        if not new_ids:
            case["needs_relabel"] = True
            case["relabel_reason"] = "June corpus evidence ids could not be migrated (see evidence_id_migration_20261022.json)"
    if isinstance(case.get("reason"), str):
        case["reason"] = ID_RE.sub(
            lambda m: ",".join(mapping[m.group(0)]["new_ids"])
            if mapping.get(m.group(0), {}).get("status") == "mapped" else m.group(0),
            case["reason"],
        )
    return case


def apply(files: list[Path], mapping: dict[str, dict[str, Any]]) -> dict[str, int]:
    stats = {"files_changed": 0, "cases_changed": 0, "cases_needs_relabel": 0}
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        out, changed = [], False
        for line in lines:
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                out.append(line)
                continue
            before = json.dumps(case, ensure_ascii=False, sort_keys=True)
            case = migrate_case(case, mapping)
            if json.dumps(case, ensure_ascii=False, sort_keys=True) == before:
                out.append(line)  # untouched lines keep their exact bytes, so the git diff stays reviewable
                continue
            changed = True
            stats["cases_changed"] += 1
            stats["cases_needs_relabel"] += int(bool(case.get("needs_relabel")))
            compact = '":"' in line or '","' in line
            out.append(json.dumps(case, ensure_ascii=False, separators=(",", ":") if compact else None))
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
            stats["files_changed"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, default=GOLD_DIR)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--apply", action="store_true", help="rewrite gold files; default only writes the mapping")
    args = parser.parse_args()

    files = [p for p in gold_files(args.gold_dir)]
    mapping = build_mapping(args.corpus, files)
    args.mapping.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mapped = sum(1 for v in mapping.values() if v["status"] == "mapped")
    print(f"old ids: {len(mapping)}, mapped: {mapped}, unmapped: {len(mapping) - mapped} -> {args.mapping}")
    if args.apply:
        print(json.dumps(apply(files, mapping), ensure_ascii=False))


if __name__ == "__main__":
    main()
