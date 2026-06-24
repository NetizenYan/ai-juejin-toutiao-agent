"""Profile the local 3G+ JJRB/RMRB raw datasets.

The script is local-only: it reads metadata, dates, section/page labels, and
counts. It does not crawl, download, build indexes, connect to Qdrant, or copy
large article bodies into reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree.ElementTree import iterparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "reports" / "raw_3g_dataset_profile_2026_06_21.json"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "docs" / "raw_3g_dataset_profile_2026_06_21.md"
DEFAULT_BAIDU_ROOT = Path("D:/Files/BaiDu")


DOMAIN_RULES: list[tuple[str, list[str]]] = [
    ("capital_market", ["资本市场", "证券", "财经", "财金", "金融", "银行", "保险"]),
    ("consumer_market", ["消费", "文旅", "文化产业", "旅游", "服务"]),
    ("industry_technology", ["产经", "产业", "企业", "公司", "创新", "新知", "科技", "数字", "数据", "制造"]),
    ("foreign_trade_global", ["国际", "环球", "世界经济", "一带一路", "外贸", "进出口", "港澳台"]),
    ("regional_local", ["地方", "区域", "地区", "城市"]),
    ("agriculture_rural", ["三农", "农业", "乡村", "农村", "农田"]),
    ("green_energy", ["生态", "绿色", "能源", "环保", "碳"]),
    ("real_estate", ["地产", "房产", "住房", "楼市"]),
    ("macro_policy", ["要闻", "宏观", "政策", "理论", "时评", "关注", "两会", "文件", "公告", "评论"]),
]


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def pct(part: int, total: int) -> float:
    return round(part * 100 / total, 2) if total else 0.0


def top_rows(counter: Counter[str], total: int, limit: int = 50) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count, "percentage": pct(count, total)}
        for label, count in counter.most_common(limit)
    ]


def parse_date(value: str) -> datetime | None:
    text = norm(value)
    if not text:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        try:
            return datetime(int(match.group(0)), 1, 1)
        except ValueError:
            return None
    return None


def year_from_name(path: Path) -> str | None:
    match = re.search(r"(19|20)\d{2}", path.name)
    return match.group(0) if match else None


def classify_section(section: str) -> str:
    text = norm(section)
    for label, keywords in DOMAIN_RULES:
        if any(keyword in text for keyword in keywords):
            return label
    return "other"


def file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "size_mb": round(path.stat().st_size / 1048576, 2),
        "last_write_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def find_jjrb_csv(root: Path) -> Path:
    candidates = list(root.glob("*2010-2026.6.csv"))
    if not candidates:
        candidates = list(root.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError(f"JJRB CSV not found under {root}")
    return max(candidates, key=lambda path: path.stat().st_size)


def find_rmrb_dir(root: Path) -> Path | None:
    direct = root / "RMRB数据"
    if direct.exists():
        return direct
    for path in root.iterdir():
        if path.is_dir() and "RMRB" in path.name:
            return path
    return None


def profile_jjrb(root: Path, top_limit: int) -> dict[str, Any]:
    path = find_jjrb_csv(root)
    started = time.perf_counter()
    section_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    domain_counter: Counter[str] = Counter()
    row_count = 0
    date_min: datetime | None = None
    date_max: datetime | None = None
    fieldnames: list[str] = []

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            row_count += 1
            section = norm(row.get("版面")) or "<empty>"
            section_counter[section] += 1
            domain_counter[classify_section(section)] += 1
            dt = parse_date(row.get("日期") or "")
            if dt:
                year_counter[str(dt.year)] += 1
                date_min = dt if date_min is None or dt < date_min else date_min
                date_max = dt if date_max is None or dt > date_max else date_max

    elapsed = round(time.perf_counter() - started, 2)
    return {
        "source": "jjrb",
        "source_name": "经济日报",
        "file": file_info(path),
        "fieldnames": fieldnames,
        "row_count": row_count,
        "date_min": date_min.date().isoformat() if date_min else None,
        "date_max": date_max.date().isoformat() if date_max else None,
        "year_distribution_top": top_rows(year_counter, row_count, top_limit),
        "section_unique_count": len(section_counter),
        "section_distribution_top": top_rows(section_counter, row_count, top_limit),
        "domain_hint_distribution": top_rows(domain_counter, row_count, top_limit),
        "elapsed_seconds": elapsed,
    }


def col_index(cell_ref: str) -> int:
    letters = re.sub(r"\d+", "", cell_ref or "")
    total = 0
    for char in letters:
        if "A" <= char <= "Z":
            total = total * 26 + (ord(char) - ord("A") + 1)
    return max(0, total - 1)


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    name = "xl/sharedStrings.xml"
    if name not in zf.namelist():
        return []
    strings: list[str] = []
    with zf.open(name) as handle:
        for event, elem in iterparse(handle, events=("end",)):
            if elem.tag.endswith("}si") or elem.tag == "si":
                texts: list[str] = []
                for child in elem.iter():
                    if child.tag.endswith("}t") or child.tag == "t":
                        if child.text:
                            texts.append(child.text)
                strings.append("".join(texts))
                elem.clear()
    return strings


def cell_value(cell: Any, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts: list[str] = []
        for child in cell.iter():
            if child.tag.endswith("}t") or child.tag == "t":
                if child.text:
                    texts.append(child.text)
        return "".join(texts)
    value = ""
    for child in cell:
        if child.tag.endswith("}v") or child.tag == "v":
            value = child.text or ""
            break
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    return value


def iter_xlsx_rows(path: Path) -> Iterable[list[str]]:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sheet_names = [
            name
            for name in zf.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ]
        if not sheet_names:
            return
        with zf.open(sorted(sheet_names)[0]) as handle:
            for event, elem in iterparse(handle, events=("end",)):
                if not (elem.tag.endswith("}row") or elem.tag == "row"):
                    continue
                cells: dict[int, str] = {}
                max_col = -1
                for cell in elem:
                    if not (cell.tag.endswith("}c") or cell.tag == "c"):
                        continue
                    idx = col_index(cell.attrib.get("r", ""))
                    cells[idx] = cell_value(cell, shared)
                    max_col = max(max_col, idx)
                elem.clear()
                yield [cells.get(i, "") for i in range(max_col + 1)]


def select_rmrb_files(root: Path, years: set[str] | None) -> list[Path]:
    rmrb_dir = find_rmrb_dir(root)
    if not rmrb_dir:
        return []
    files = [
        path
        for path in rmrb_dir.rglob("*.xlsx")
        if path.is_file() and not path.name.startswith("~$")
    ]
    if years:
        files = [path for path in files if (year_from_name(path) or "") in years]
    return sorted(files)


def profile_rmrb(root: Path, top_limit: int, years: set[str] | None) -> dict[str, Any]:
    files = select_rmrb_files(root, years)
    started = time.perf_counter()
    section_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    domain_counter: Counter[str] = Counter()
    per_file: list[dict[str, Any]] = []
    row_count = 0
    date_min: datetime | None = None
    date_max: datetime | None = None
    fieldname_counter: Counter[str] = Counter()

    for path in files:
        file_rows = 0
        header_map: dict[str, int] | None = None
        header_names: list[str] = []
        for row_no, row in enumerate(iter_xlsx_rows(path), start=1):
            if not row:
                continue
            if header_map is None:
                header_names = [norm(cell) for cell in row if norm(cell)]
                for name in header_names:
                    fieldname_counter[name] += 1
                header_map = {name: idx for idx, name in enumerate([norm(cell) for cell in row]) if name}
                continue
            file_rows += 1
            row_count += 1

            def get(name: str) -> str:
                idx = header_map.get(name, -1) if header_map else -1
                return row[idx] if 0 <= idx < len(row) else ""

            section = norm(get("报纸版次")) or "<empty>"
            section_counter[section] += 1
            domain_counter[classify_section(section)] += 1

            dt = parse_date(get("日期"))
            if dt:
                year_counter[str(dt.year)] += 1
                date_min = dt if date_min is None or dt < date_min else date_min
                date_max = dt if date_max is None or dt > date_max else date_max

        per_file.append(
            {
                "file": str(path),
                "year": year_from_name(path),
                "size_mb": round(path.stat().st_size / 1048576, 2),
                "row_count": file_rows,
                "fieldnames": header_names,
            }
        )

    elapsed = round(time.perf_counter() - started, 2)
    total_size = sum(path.stat().st_size for path in files)
    return {
        "source": "rmrb",
        "source_name": "人民日报",
        "file_count": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1048576, 2),
        "years_filter": sorted(years) if years else "all",
        "files": per_file,
        "fieldnames_observed": sorted(fieldname_counter),
        "row_count": row_count,
        "date_min": date_min.date().isoformat() if date_min else None,
        "date_max": date_max.date().isoformat() if date_max else None,
        "year_distribution_top": top_rows(year_counter, row_count, top_limit),
        "section_unique_count": len(section_counter),
        "section_distribution_top": top_rows(section_counter, row_count, top_limit),
        "domain_hint_distribution": top_rows(domain_counter, row_count, top_limit),
        "elapsed_seconds": elapsed,
    }


def load_existing_econ_candidate_profile(top_limit: int) -> dict[str, Any]:
    report_path = PROJECT_ROOT / "work" / "econ_rag_experiment" / "clean_merged_recent_econ_report.json"
    jsonl_path = PROJECT_ROOT / "work" / "econ_rag_experiment" / "clean_merged_recent_econ.jsonl"
    if not report_path.exists():
        return {"available": False}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    section_counter: Counter[str] = Counter()
    domain_counter: Counter[str] = Counter()
    row_count = 0
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                row_count += 1
                section = norm(row.get("section")) or "<empty>"
                section_counter[section] += 1
                domain_counter[classify_section(section)] += 1
    return {
        "available": True,
        "report_path": str(report_path),
        "jsonl_path": str(jsonl_path) if jsonl_path.exists() else None,
        "source_counts": data.get("source_counts"),
        "source_stats": data.get("source_stats"),
        "dedupe": data.get("dedupe"),
        "recent_windows": data.get("recent_windows"),
        "section_distribution_top": top_rows(section_counter, row_count, top_limit),
        "domain_hint_distribution": top_rows(domain_counter, row_count, top_limit),
    }


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    jjrb = report["sources"]["jjrb"]
    rmrb = report["sources"]["rmrb"]
    econ = report["existing_econ_candidate"]
    section_rows = [
        [row["label"], row["count"], f'{row["percentage"]}%']
        for row in jjrb["section_distribution_top"][:30]
    ]
    rmrb_rows = [
        [row["label"], row["count"], f'{row["percentage"]}%']
        for row in rmrb["section_distribution_top"][:30]
    ]
    domain_rows = [
        ["jjrb", row["label"], row["count"], f'{row["percentage"]}%']
        for row in jjrb["domain_hint_distribution"]
    ] + [
        ["rmrb", row["label"], row["count"], f'{row["percentage"]}%']
        for row in rmrb["domain_hint_distribution"]
    ]

    text = f"""# Raw 3G+ Dataset Profile Report

Generated at: `{report["generated_at"]}`

This is a local-only profile of the 3G+ raw datasets. It does not crawl, download, build Qdrant collections, write MySQL, or copy large full text into the report.

## 1. Scope

The profile covers:

- JJRB / 经济日报 CSV: `{jjrb["file"]["path"]}`
- RMRB / 人民日报 Excel files: `{rmrb["file_count"]}` files, years filter `{rmrb["years_filter"]}`
- Existing cleaned economic candidate report, if present

## 2. Raw Source Inventory

{md_table(["source", "rows/profiled rows", "size", "date_min", "date_max", "section_unique_count"], [
    ["jjrb", jjrb["row_count"], f'{jjrb["file"]["size_mb"]} MB', jjrb["date_min"], jjrb["date_max"], jjrb["section_unique_count"]],
    ["rmrb", rmrb["row_count"], f'{rmrb["total_size_mb"]} MB', rmrb["date_min"], rmrb["date_max"], rmrb["section_unique_count"]],
])}

## 3. JJRB Raw Section Top 30

{md_table(["section", "count", "percentage"], section_rows)}

## 4. RMRB Section Top 30

{md_table(["section", "count", "percentage"], rmrb_rows)}

## 5. Domain Hints From Section Names

These are only profile hints for future internal RAG candidate design. They do not change Router, Validator, or collection config.

{md_table(["source", "domain_hint", "count", "percentage"], domain_rows)}

## 6. Existing Econ Candidate Link

Existing cleaned economic candidate is available: `{econ.get("available")}`.

```json
{json.dumps({
    "source_counts": econ.get("source_counts"),
    "dedupe": econ.get("dedupe"),
    "recent_windows": econ.get("recent_windows"),
}, ensure_ascii=False, indent=2)[:4000]}
```

## 7. Recommended Next Step

Start with local-only candidate profiles rather than indexing:

1. `econ_finance_query`: keep current enforce setup and current collection.
2. `policy_macro`: use the manual sample pack first, then shadow only.
3. `capital_market`, `consumer_market`, `industry_technology`, `foreign_trade_global`: create profile-only candidate plans from raw section/domain hints before building any collection.
4. Do not upload raw CSV/XLSX, cleaned full-text JSONL, or Qdrant dumps to GitHub.

## Final Decision

```text
可以继续用本地 3G+ 数据做内部画像、候选集设计和 RAG 召回验证；
下一步先做多类目 candidate profile，不直接新建 collection。
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.baidu_root)
    years = None if args.rmrb_years == ["all"] else set(args.rmrb_years)
    started = time.perf_counter()
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project": "toutiao_agent_unified",
        "scope_guardrails": [
            "local raw data profile only",
            "no crawling",
            "no external site access",
            "no download",
            "no Qdrant collection changes",
            "no MySQL writes",
            "no frontend changes",
            "no Validator enforce changes",
        ],
        "baidu_root": str(root),
        "domain_hint_rules": [
            {"domain_hint": label, "keywords": keywords}
            for label, keywords in DOMAIN_RULES
        ],
        "sources": {
            "jjrb": profile_jjrb(root, args.top_limit),
            "rmrb": profile_rmrb(root, args.top_limit, years),
        },
        "existing_econ_candidate": load_existing_econ_candidate_profile(args.top_limit),
    }
    report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile local JJRB/RMRB raw datasets.")
    parser.add_argument("--baidu-root", default=str(DEFAULT_BAIDU_ROOT))
    parser.add_argument("--rmrb-years", nargs="+", default=["2025", "2026"], help="Years to profile, or 'all'.")
    parser.add_argument("--top-limit", type=int, default=80)
    parser.add_argument("--json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    report = run(args)
    output_json = Path(args.json)
    output_md = Path(args.md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, output_md)
    print(json.dumps({
        "json": str(output_json),
        "md": str(output_md),
        "elapsed_seconds": report["elapsed_seconds"],
        "jjrb_rows": report["sources"]["jjrb"]["row_count"],
        "jjrb_sections": report["sources"]["jjrb"]["section_unique_count"],
        "rmrb_rows": report["sources"]["rmrb"]["row_count"],
        "rmrb_sections": report["sources"]["rmrb"]["section_unique_count"],
        "rmrb_years_filter": report["sources"]["rmrb"]["years_filter"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
