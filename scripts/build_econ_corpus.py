"""Build the economy/policy RAG corpus (JSONL) from the raw 经济日报 CSV and 人民日报 xlsx files.

Replaces the June 2026 cleaning step, whose script and output (work/econ_rag_experiment/
clean_merged_recent_econ.jsonl) were never committed. The output feeds scripts/rebuild_pipeline.py.

Pipeline: date window -> text cleanup -> noise / too-short filter -> economy relevance -> dedupe.

Evidence id rule (documented so it can be reproduced):
    source_doc_id = sha256("{source}|{YYYY-MM-DD}|{section}|{title}|{content[:200]}")[:16]
    evidence_id   = "news:{source}:{source_doc_id}"
where section/title/content are the cleaned values. The June ids could not be reproduced from the
raw data, so ids produced here differ from those in eval/gold (see docs for the migration).

Usage (project root):
    .venv/bin/python -m scripts.build_econ_corpus \
        --start 2025-06-10 --end 2026-06-10 \
        --output data/processed/econ_corpus_20250610_20260610.jsonl
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from scripts.report_raw_3g_dataset_profile import iter_xlsx_rows

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JJRB_CSV = PROJECT_ROOT / "data" / "raw" / "经济日报2010-2026.6.csv"
DEFAULT_RMRB_DIR = PROJECT_ROOT / "data" / "raw" / "RMRB数据" / "分年份保存数据"
MIN_CONTENT_CHARS = 80
SUMMARY_CHARS = 200
ECON_MATCH_CHARS = 500  # title + head of body; matching the full body marks nearly everything as relevant

# Page furniture rather than articles (from the in-window title frequency profile).
NOISE_TITLES = {"图片新闻", "图片报道", "来稿邮箱", "投稿网站", "广告", "导读", "目录", "经济日报多媒体数字报刊"}
NOISE_TITLE_RE = re.compile(r"^(本版责编|责任编辑|版面编辑|本版编辑|来稿邮箱|投稿|广告)")

# Topic keywords from docs/news_dataset_profile_2026_06_21.md §10, minus politics_governance.
ECON_TOPICS: dict[str, tuple[str, ...]] = {
    "economy_finance": ("经济", "财经", "金融", "财政", "货币", "投资", "GDP", "CPI", "PPI", "PMI", "汇率", "债券",
                        "人民银行", "商业银行", "银行业", "信贷", "融资", "贷款", "税收", "营收", "利润", "经济增长",
                        "稳增长", "资本市场", "民营经济", "实体经济", "高质量发展", "新质生产力"),
    "stock_market_related": ("A股", "股市", "股票", "上市公司", "证券", "证监会", "交易所", "IPO", "并购", "回购",
                             "分红", "创业板", "北交所", "公募基金", "私募基金", "ETF", "券商"),
    "real_estate": ("房地产", "楼市", "房价", "住房", "商品房", "二手房", "房贷", "土地出让", "保障房", "城中村",
                    "保交楼", "开发商"),
    "foreign_trade": ("外贸", "进出口", "出口", "进口", "全球贸易", "关税", "海关", "跨境电商", "一带一路", "自贸区",
                      "外资", "外商投资", "RCEP"),
    "energy_new_energy": ("能源", "新能源", "光伏", "风电", "储能", "锂电", "充电桩", "煤炭", "石油", "天然气",
                          "电力", "绿电", "氢能", "碳市场", "碳排放", "核电"),
    "consumer_market": ("消费", "零售", "餐饮", "文旅", "旅游", "票房", "电商", "家电", "汽车消费", "以旧换新",
                        "服务消费", "居民收入"),
    "technology_industry": ("人工智能", "AI", "大模型", "算力", "芯片", "半导体", "机器人", "数字化", "云计算",
                            "数据中心", "低空经济", "智能制造", "数字经济", "工业互联网"),
    "industry_policy": ("制造业", "产业链", "供应链", "专精特新", "现代化产业体系", "新能源汽车", "钢铁", "医药",
                        "农业"),
    "policy_macro": ("宏观", "发改委", "财政部", "央行", "工信部", "政府工作报告", "产业政策", "促消费", "扩大内需",
                     "稳就业", "十五五", "营商环境"),
}
ECON_SECTION_RE = re.compile(r"财经|财金|产经|经济|金融|资本市场|宏观|企业|产业|市场|消费|区域|投资|理财")

_RMRB_HEADER_RE = re.compile(r"^\s*人民日报\d{4}年\d{1,2}月\d{1,2}日\s*[A-Za-z]{3}\s*")
_MOJIBAKE_Q_RE = re.compile(r"(?<=[一-鿿，。：；、“”（）])\?|\?(?=[一-鿿，。：；、“”（）])")
_WS_RE = re.compile(r"[ \t　\xa0]+")


def parse_date(value: str) -> datetime | None:
    text = (value or "").strip()[:10]
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def clean_text(text: str, *, source: str = "") -> str:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if source == "rmrb":
        value = _RMRB_HEADER_RE.sub("", value)
    value = _MOJIBAKE_Q_RE.sub("", value)  # CSV export turned some spaces into "?" between CJK chars
    lines = [_WS_RE.sub(" ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def clean_inline(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\n", " ")).strip()


def is_noise_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title or "")
    return not compact or compact in NOISE_TITLES or bool(NOISE_TITLE_RE.match(compact))


_SOURCE_NAME_RE = re.compile(r"经济日报|人民日报|中国经济网")


def econ_topics(title: str, content: str, section: str) -> list[str]:
    # Bylines like "经济日报记者" would otherwise match "经济" and mark every 经济日报 article relevant.
    haystack = _SOURCE_NAME_RE.sub("", f"{title}\n{content[:ECON_MATCH_CHARS]}")
    topics = [name for name, words in ECON_TOPICS.items() if any(word in haystack for word in words)]
    if not topics and ECON_SECTION_RE.search(section or ""):
        topics.append("econ_section")
    return topics


def source_doc_id(source: str, date: datetime, section: str, title: str, content: str) -> str:
    key = f"{source}|{date.strftime('%Y-%m-%d')}|{section}|{title}|{content[:SUMMARY_CHARS]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def iter_jjrb(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield {"source": "jjrb", "date": row.get("日期") or "", "section": row.get("版面") or "",
                   "title": row.get("标题") or "", "content": row.get("内容") or "", "url": row.get("链接") or ""}


def iter_rmrb(directory: Path, years: Iterable[int]) -> Iterator[dict[str, str]]:
    for year in sorted(set(years)):
        path = directory / f"人民日报{year}年文本数据.xlsx"
        if not path.exists():
            continue
        rows = iter_xlsx_rows(path)
        header = [cell.strip() for cell in next(rows, [])]
        index = {name: i for i, name in enumerate(header)}
        for row in rows:
            def col(name: str) -> str:
                i = index.get(name)
                return row[i] if i is not None and i < len(row) else ""
            yield {"source": "rmrb", "date": col("日期"), "section": col("报纸版次"), "title": col("标题"),
                   "content": col("文本内容"), "url": ""}


def build_records(raw_rows: Iterable[dict[str, str]], start: datetime, end: datetime,
                  stats: Counter[str]) -> list[dict[str, Any]]:
    """Return cleaned records in input order.

    Two rows are the same article if they share the evidence-id key (source/date/section/title/
    first 200 chars), e.g. a page scraped twice where one copy kept an extra sub-heading; the longer
    copy wins. Rows with the same title and opening 300 chars are also treated as duplicates.
    """
    by_id: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_rows:
        stats["scanned"] += 1
        date = parse_date(raw["date"])
        if date is None or not (start <= date <= end):
            continue
        stats["in_window"] += 1
        source = raw["source"]
        title = clean_inline(raw["title"])
        section = clean_inline(raw["section"])
        content = clean_text(raw["content"], source=source)
        if is_noise_title(title):
            stats["noise_dropped"] += 1
            continue
        if len(content) < MIN_CONTENT_CHARS:
            stats["too_short"] += 1
            continue
        topics = econ_topics(title, content, section)
        if not topics:
            stats["not_econ"] += 1
            continue
        doc_hash = source_doc_id(source, date, section, title, content)
        evidence_id = f"news:{source}:{doc_hash}"
        existing = by_id.get(evidence_id)
        if existing is not None:
            stats["duplicates_removed"] += 1
            if len(content) > len(existing["content"]):
                existing.update(content=content, summary=clean_inline(content[:SUMMARY_CHARS]))
            continue
        fingerprint = re.sub(r"\s+", "", content[:300])
        dedupe_key = (source, re.sub(r"\s+", "", title), fingerprint)
        if dedupe_key in seen:
            stats["duplicates_removed"] += 1
            continue
        seen.add(dedupe_key)
        by_id[evidence_id] = {
            "source": source,
            "source_doc_id": doc_hash,
            "doc_id": f"{source}:{doc_hash}",
            "evidence_id": evidence_id,
            "title": title,
            "summary": clean_inline(content[:SUMMARY_CHARS]),
            "content": content,
            "url": raw.get("url") or "",
            "publish_time": date.strftime("%Y-%m-%d 00:00:00"),
            "publish_ts": int(date.timestamp()),
            "section": section,
            "category": topics[0],
            "topics": topics,
        }
    for record in by_id.values():
        stats[f"kept_{record['source']}"] += 1
    return list(by_id.values())


def run(args: argparse.Namespace) -> dict[str, Any]:
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stats: Counter[str] = Counter()
    ids: set[str] = set()

    def raw_rows() -> Iterator[dict[str, str]]:
        yield from iter_jjrb(Path(args.jjrb_csv))
        yield from iter_rmrb(Path(args.rmrb_dir), range(start.year, end.year + 1))

    with output.open("w", encoding="utf-8") as handle:
        for record in build_records(raw_rows(), start, end, stats):
            if record["evidence_id"] in ids:
                raise RuntimeError(f"evidence id collision: {record['evidence_id']}")
            ids.add(record["evidence_id"])
            stats[f"topic_{record['category']}"] += 1
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    report = {"window": [args.start, args.end], "output": str(output), "kept": len(ids), **dict(stats)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--start", default="2025-06-10")
    parser.add_argument("--end", default="2026-06-10")
    parser.add_argument("--jjrb-csv", default=str(DEFAULT_JJRB_CSV))
    parser.add_argument("--rmrb-dir", default=str(DEFAULT_RMRB_DIR))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "data" / "processed" / "econ_corpus_20250610_20260610.jsonl"))
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
