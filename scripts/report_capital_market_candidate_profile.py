"""Profile local capital-market candidate documents from the 3G+ raw dataset.

Local-only profile:
- no crawling
- no download
- no Qdrant collection changes
- no MySQL writes
- no long full-text output
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from report_raw_3g_dataset_profile import (
    find_jjrb_csv,
    iter_xlsx_rows,
    norm,
    parse_date,
    select_rmrb_files,
    top_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BAIDU_ROOT = Path("D:/Files/BaiDu")
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "reports" / "capital_market_candidate_profile_2026_06_21.json"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "docs" / "capital_market_candidate_profile_2026_06_21.md"
AS_OF = datetime(2026, 6, 21)
CUTOFF = datetime(2025, 6, 21)

SECTION_KEYWORDS = [
    "资本市场",
    "证券",
    "财金",
    "财经",
    "金融",
    "银行",
    "保险",
    "基金",
    "财富",
    "公司时讯",
    "证券·公司",
]

TITLE_KEYWORDS = [
    "资本市场",
    "证监会",
    "证券",
    "A股",
    "股市",
    "股票",
    "上市公司",
    "交易所",
    "IPO",
    "再融资",
    "并购重组",
    "退市",
    "债券",
    "基金",
    "银行",
    "保险",
    "券商",
    "金融",
    "投资者",
    "融资",
    "利率",
]

CONTENT_KEYWORDS = [
    "资本市场",
    "证监会",
    "上市公司",
    "投资者保护",
    "并购重组",
    "股票市场",
    "证券市场",
    "金融市场",
    "直接融资",
    "长期资金",
]

INDUSTRY_TAG_HINTS = {
    "banking": ["银行", "信贷", "贷款", "利率"],
    "securities": ["证券", "券商", "资本市场", "IPO", "再融资", "并购重组"],
    "insurance": ["保险", "险资"],
    "broad_market": ["A股", "股市", "股票市场", "长期资金", "投资者"],
}


@dataclass
class ProfileStats:
    scanned: int = 0
    date_window: int = 0
    matched: int = 0
    section_matched: int = 0
    title_matched: int = 0
    content_prefix_matched: int = 0
    too_short: int = 0
    invalid_date: int = 0


def pct(part: int, total: int) -> float:
    return round(part * 100 / total, 2) if total else 0.0


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword and keyword in text]


def industry_tags_for(text: str) -> list[str]:
    tags: list[str] = []
    for tag, keywords in INDUSTRY_TAG_HINTS.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag)
    return tags or ["broad_market"]


def add_sample(samples: list[dict[str, Any]], item: dict[str, Any], limit: int = 25) -> None:
    if len(samples) < limit:
        samples.append(item)


def profile_jjrb(root: Path, sample_limit: int) -> tuple[ProfileStats, Counter[str], Counter[str], Counter[str], list[dict[str, Any]]]:
    path = find_jjrb_csv(root)
    stats = ProfileStats()
    section_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_no, row in enumerate(reader, start=2):
            stats.scanned += 1
            dt = parse_date(row.get("日期") or "")
            if not dt:
                stats.invalid_date += 1
                continue
            if not (CUTOFF <= dt <= AS_OF):
                continue
            stats.date_window += 1
            title = norm(row.get("标题"))
            section = norm(row.get("版面"))
            content = norm(row.get("内容"))
            if len(title) + len(content) < 80:
                stats.too_short += 1
                continue

            section_hits = keyword_hits(section, SECTION_KEYWORDS)
            title_hits = keyword_hits(title, TITLE_KEYWORDS)
            content_hits = keyword_hits(content[:1200], CONTENT_KEYWORDS)
            if not (section_hits or title_hits or content_hits):
                continue

            stats.matched += 1
            stats.section_matched += 1 if section_hits else 0
            stats.title_matched += 1 if title_hits else 0
            stats.content_prefix_matched += 1 if content_hits else 0
            section_counter[section or "<empty>"] += 1
            year_counter[str(dt.year)] += 1
            tags = industry_tags_for(f"{section} {title} {content[:1200]}")
            for tag in tags:
                tag_counter[tag] += 1
            add_sample(
                samples,
                {
                    "source": "jjrb",
                    "row_no": row_no,
                    "date": dt.date().isoformat(),
                    "section": section,
                    "title": title[:160],
                    "matched_keywords": sorted(set(section_hits + title_hits + content_hits)),
                    "industry_tags": tags,
                    "url": norm(row.get("链接")),
                },
                sample_limit,
            )
    return stats, section_counter, year_counter, tag_counter, samples


def profile_rmrb(root: Path, sample_limit: int, years: set[str]) -> tuple[ProfileStats, Counter[str], Counter[str], Counter[str], list[dict[str, Any]]]:
    stats = ProfileStats()
    section_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    for path in select_rmrb_files(root, years):
        header_map: dict[str, int] | None = None
        for row_no, row in enumerate(iter_xlsx_rows(path), start=1):
            if not row:
                continue
            if header_map is None:
                names = [norm(cell) for cell in row]
                header_map = {name: idx for idx, name in enumerate(names) if name}
                continue
            stats.scanned += 1

            def get(name: str) -> str:
                idx = header_map.get(name, -1) if header_map else -1
                return row[idx] if 0 <= idx < len(row) else ""

            dt = parse_date(get("日期"))
            if not dt:
                stats.invalid_date += 1
                continue
            if not (CUTOFF <= dt <= AS_OF):
                continue
            stats.date_window += 1
            title = norm(get("标题"))
            section = norm(get("报纸版次"))
            content = norm(get("文本内容") or get("内容"))
            if len(title) + len(content) < 80:
                stats.too_short += 1
                continue

            section_hits = keyword_hits(section, SECTION_KEYWORDS)
            title_hits = keyword_hits(title, TITLE_KEYWORDS)
            content_hits = keyword_hits(content[:1200], CONTENT_KEYWORDS)
            if not (section_hits or title_hits or content_hits):
                continue

            stats.matched += 1
            stats.section_matched += 1 if section_hits else 0
            stats.title_matched += 1 if title_hits else 0
            stats.content_prefix_matched += 1 if content_hits else 0
            section_counter[section or "<empty>"] += 1
            year_counter[str(dt.year)] += 1
            tags = industry_tags_for(f"{section} {title} {content[:1200]}")
            for tag in tags:
                tag_counter[tag] += 1
            add_sample(
                samples,
                {
                    "source": "rmrb",
                    "file": path.name,
                    "row_no": row_no,
                    "date": dt.date().isoformat(),
                    "section": section,
                    "title": title[:160],
                    "matched_keywords": sorted(set(section_hits + title_hits + content_hits)),
                    "industry_tags": tags,
                },
                sample_limit,
            )
    return stats, section_counter, year_counter, tag_counter, samples


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def build_report(root: Path, years: set[str], sample_limit: int) -> dict[str, Any]:
    started = time.perf_counter()
    jjrb_stats, jjrb_sections, jjrb_years, jjrb_tags, jjrb_samples = profile_jjrb(root, sample_limit)
    rmrb_stats, rmrb_sections, rmrb_years, rmrb_tags, rmrb_samples = profile_rmrb(root, sample_limit, years)

    total_scanned = jjrb_stats.scanned + rmrb_stats.scanned
    total_date_window = jjrb_stats.date_window + rmrb_stats.date_window
    total_matched = jjrb_stats.matched + rmrb_stats.matched
    combined_sections = jjrb_sections + rmrb_sections
    combined_years = jjrb_years + rmrb_years
    combined_tags = jjrb_tags + rmrb_tags

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project": "toutiao_agent_unified",
        "domain_id": "capital_market",
        "scope_guardrails": [
            "local profile only",
            "no crawling",
            "no external site access",
            "no download",
            "no Qdrant collection changes",
            "no MySQL writes",
            "no frontend changes",
            "no Validator enforce changes",
            "no stock price prediction",
            "no long full-text output"
        ],
        "query_boundary": {
            "allowed": [
                "capital-market policy/regulation explanation",
                "sector-level possible influence explanation",
                "citation-backed news evidence"
            ],
            "forbidden": [
                "individual stock price prediction",
                "buy/sell advice",
                "guaranteed gain or deterministic market outcome"
            ]
        },
        "source_stats": {
            "jjrb": asdict(jjrb_stats),
            "rmrb": asdict(rmrb_stats),
            "combined": {
                "scanned": total_scanned,
                "date_window": total_date_window,
                "matched": total_matched,
                "matched_rate_of_date_window": pct(total_matched, total_date_window)
            }
        },
        "distributions": {
            "top_sections": top_rows(combined_sections, total_matched, 50),
            "top_years": top_rows(combined_years, total_matched, 20),
            "industry_tag_hints": top_rows(combined_tags, total_matched, 20),
            "jjrb_top_sections": top_rows(jjrb_sections, jjrb_stats.matched, 30),
            "rmrb_top_sections": top_rows(rmrb_sections, rmrb_stats.matched, 30)
        },
        "sample_titles": {
            "jjrb": jjrb_samples,
            "rmrb": rmrb_samples
        },
        "shadow_readiness": {
            "profile_exists": True,
            "candidate_count_at_least_30": total_matched >= 30,
            "source_coverage_at_least_2": jjrb_stats.matched > 0 and rmrb_stats.matched > 0,
            "manual_review_done": False,
            "citation_detail_gate_done": False,
            "no_answer_tests_done": False,
            "financial_advice_guard_required": True,
            "recommended_mode": "profile_only_now_then_shadow_after_manual_review"
        },
        "next_steps": [
            "manual review 30-60 capital_market samples",
            "split policy/regulation news from institution/company financial news",
            "create shadow query set with no-answer and advice-boundary probes",
            "do not build a collection until profile and shadow gates pass"
        ],
        "final_decision": "capital_market has enough local signal for candidate profiling, but is not ready for enforce or a new collection",
        "elapsed_seconds": round(time.perf_counter() - started, 2)
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    stats = report["source_stats"]
    sections = report["distributions"]["top_sections"][:25]
    years = report["distributions"]["top_years"][:10]
    tags = report["distributions"]["industry_tag_hints"]
    samples = report["sample_titles"]

    text = f"""# Capital Market Candidate Profile Report

Generated at: `{report["generated_at"]}`

This is a local-only candidate profile for `capital_market`. It does not crawl, download, build a Qdrant collection, modify RAG, modify frontend, or expand Validator enforce.

## 1. Scope

Profile source:

```text
JJRB / 经济日报 local CSV
RMRB / 人民日报 local XLSX, years 2025 and 2026
```

The profile uses section, title, and short content-prefix keyword matches. It does not store long full text in the report.

## 2. Candidate Counts

{md_table(["source", "scanned", "date_window", "matched", "section_matched", "title_matched", "content_prefix_matched"], [
    ["jjrb", stats["jjrb"]["scanned"], stats["jjrb"]["date_window"], stats["jjrb"]["matched"], stats["jjrb"]["section_matched"], stats["jjrb"]["title_matched"], stats["jjrb"]["content_prefix_matched"]],
    ["rmrb", stats["rmrb"]["scanned"], stats["rmrb"]["date_window"], stats["rmrb"]["matched"], stats["rmrb"]["section_matched"], stats["rmrb"]["title_matched"], stats["rmrb"]["content_prefix_matched"]],
    ["combined", stats["combined"]["scanned"], stats["combined"]["date_window"], stats["combined"]["matched"], "", "", ""],
])}

Matched rate of date window: `{stats["combined"]["matched_rate_of_date_window"]}%`.

## 3. Top Sections

{md_table(["section", "count", "percentage"], [[row["label"], row["count"], f'{row["percentage"]}%'] for row in sections])}

## 4. Year Distribution

{md_table(["year", "count", "percentage"], [[row["label"], row["count"], f'{row["percentage"]}%'] for row in years])}

## 5. Industry Tag Hints

{md_table(["tag", "count", "percentage"], [[row["label"], row["count"], f'{row["percentage"]}%'] for row in tags])}

## 6. Sample Titles

JJRB examples:

{md_table(["date", "section", "title", "matched_keywords"], [[item["date"], item["section"], item["title"], ", ".join(item["matched_keywords"])] for item in samples["jjrb"][:10]])}

RMRB examples:

{md_table(["date", "section", "title", "matched_keywords"], [[item["date"], item["section"], item["title"], ", ".join(item["matched_keywords"])] for item in samples["rmrb"][:10]])}

## 7. Safety Boundary

Allowed:

```text
capital-market policy/regulation explanation
sector-level possible influence explanation
citation-backed news evidence
```

Forbidden:

```text
individual stock price prediction
buy/sell advice
guaranteed gain or deterministic market outcome
```

## 8. Shadow Readiness

```json
{json.dumps(report["shadow_readiness"], ensure_ascii=False, indent=2)}
```

## 9. Next Steps

```text
manual review 30-60 capital_market samples
split policy/regulation news from institution/company financial news
create shadow query set with no-answer and advice-boundary probes
do not build a collection until profile and shadow gates pass
```

## Final Decision

```text
capital_market has enough local signal for candidate profiling;
not ready for enforce;
not ready for a new collection.
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile local capital-market candidates.")
    parser.add_argument("--baidu-root", default=str(DEFAULT_BAIDU_ROOT))
    parser.add_argument("--rmrb-years", nargs="+", default=["2025", "2026"])
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    report = build_report(Path(args.baidu_root), set(args.rmrb_years), args.sample_limit)
    output_json = Path(args.json)
    output_md = Path(args.md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, output_md)
    print(json.dumps({
        "json": str(output_json),
        "md": str(output_md),
        "matched": report["source_stats"]["combined"]["matched"],
        "matched_rate_of_date_window": report["source_stats"]["combined"]["matched_rate_of_date_window"],
        "final_decision": report["final_decision"],
        "elapsed_seconds": report["elapsed_seconds"]
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
