"""Generate the parent-news dataset profile report.

This script reads the existing MySQL parent news table and existing experiment
logs only. It does not read Qdrant, rebuild indexes, modify collections, or
call any LLM provider.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.db_conf import AsyncSessionLocal, async_engine  # noqa: E402

DEFAULT_DOC_PATH = PROJECT_ROOT / "docs" / "news_dataset_profile_2026_06_21.md"
DEFAULT_JSON_PATH = PROJECT_ROOT / "reports" / "news_dataset_profile_2026_06_21.json"
DEFAULT_CSV_PATH = PROJECT_ROOT / "reports" / "news_dataset_profile_2026_06_21.csv"
ECON_CLEAN_REPORT = PROJECT_ROOT / "work" / "econ_rag_experiment" / "clean_merged_recent_econ_report.json"
ECON_INDEX_REPORT = PROJECT_ROOT / "work" / "econ_rag_experiment" / "econ_candidate_chunk_index_report.json"

AS_OF_DATE = date(2026, 6, 21)
PRIMARY_PRIORITY = [
    "stock_market_related",
    "real_estate",
    "foreign_trade",
    "energy_new_energy",
    "consumer_market",
    "technology_industry",
    "industry_policy",
    "policy_macro",
    "economy_finance",
    "politics_governance",
    "general_news",
    "unknown",
]

KEYWORD_RULES: dict[str, list[str]] = {
    "stock_market_related": [
        "A股", "股市", "股票", "上市公司", "证券", "证监会", "交易所", "上交所", "深交所",
        "北交所", "IPO", "并购", "回购", "分红", "沪指", "深成指", "创业板指", "上证指数",
        "股票指数", "股指", "股票板块", "行业板块", "个股", "北向资金", "公募基金", "私募基金",
        "证券投资基金", "股票型基金", "ETF", "券商", "资本市场",
    ],
    "real_estate": [
        "房地产", "楼市", "房价", "住房", "商品房", "二手房", "租赁", "房贷", "按揭",
        "土地出让", "保障房", "城中村", "保交楼", "物业", "开发商",
    ],
    "foreign_trade": [
        "外贸", "进出口", "出口", "进口", "全球贸易", "贸易", "关税", "海关", "跨境电商",
        "一带一路", "自贸区", "外资", "外商投资", "国际市场", "RCEP",
    ],
    "energy_new_energy": [
        "能源", "新能源", "光伏", "风电", "储能", "锂电", "电池", "充电桩", "煤炭",
        "石油", "天然气", "电力", "绿电", "氢能", "碳市场", "碳排放", "节能", "核电",
    ],
    "consumer_market": [
        "消费", "零售", "餐饮", "文旅", "旅游", "假期", "票房", "商场", "电商", "购物",
        "家电", "汽车消费", "以旧换新", "服务消费", "夜经济", "居民收入",
    ],
    "technology_industry": [
        "科技", "技术", "人工智能", "AI", "大模型", "算力", "芯片", "半导体", "机器人",
        "数字化", "云计算", "数据中心", "互联网", "软件", "操作系统", "量子", "卫星",
        "低空经济", "智能制造", "新质生产力",
    ],
    "industry_policy": [
        "半导体", "芯片", "人工智能", "算力", "新能源汽车", "汽车", "医药", "军工",
        "能源", "钢铁", "农业", "低空经济", "数字经济", "机器人", "光伏", "储能",
        "工业互联网", "制造业", "产业链", "供应链", "专精特新", "现代化产业体系",
    ],
    "policy_macro": [
        "政策", "宏观", "国务院", "发改委", "财政部", "央行", "证监会", "工信部",
        "政府工作报告", "两会", "高质量发展", "新质生产力", "改革", "开放", "监管",
        "产业政策", "促消费", "扩大内需", "稳就业", "稳增长", "十五五", "规划",
    ],
    "economy_finance": [
        "经济", "财经", "金融", "财政", "货币", "投资", "GDP", "CPI", "PPI", "PMI",
        "汇率", "债券", "人民银行", "商业银行", "银行业", "银行贷款", "银行信贷", "银行间",
        "信贷", "融资", "贷款", "税收", "营收", "利润",
        "经济增长", "稳增长", "资本市场", "民营经济", "实体经济", "高质量发展", "新质生产力",
    ],
    "politics_governance": [
        "习近平", "中央", "政治局", "全国人大", "政协", "政府", "治理", "党员", "会议",
        "外交", "国家安全", "地方政府", "省委", "市委", "国务院常务会议", "人大常委会",
        "纪检", "监察", "法治",
    ],
}

SOURCE_RULES: list[tuple[str, list[str]]] = [
    ("经济日报 / jjrb", ["经济日报", "jjrb"]),
    ("央视 / cctv / 新闻联播", ["新闻联播", "央视", "cctv", "CCTV"]),
    ("聚合数据", ["聚合数据", "juhe", "Juhe"]),
    ("人民日报 / rmrb", ["人民日报", "rmrb"]),
    ("新华社", ["新华社", "新华每日电讯"]),
]


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def pct(count: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(count) * 100.0 / float(total), 2)


def percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    return ordered[index]


def md_escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(md_escape(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(md_escape(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def truncate(value: str, limit: int = 90) -> str:
    text_value = norm(value)
    return text_value if len(text_value) <= limit else text_value[: limit - 1] + "…"


def match_keywords(text_blob: str, label: str) -> list[str]:
    matched: list[str] = []
    for keyword in KEYWORD_RULES[label]:
        if re.fullmatch(r"[A-Za-z0-9_+\-.]+", keyword):
            pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])"
            if re.search(pattern, text_blob, flags=re.IGNORECASE):
                matched.append(keyword)
            continue
        if keyword.lower() in text_blob.lower():
            matched.append(keyword)
    return matched


def classify(row: dict[str, Any]) -> tuple[list[str], str, dict[str, list[str]]]:
    text_blob = " ".join(
        [
            norm(row.get("title")),
            norm(row.get("description")),
            norm(row.get("content")),
            norm(row.get("category_name")),
        ]
    )
    matched_by_label: dict[str, list[str]] = {}
    labels: list[str] = []
    for label in KEYWORD_RULES:
        matched = match_keywords(text_blob, label)
        if matched:
            labels.append(label)
            matched_by_label[label] = matched[:12]

    if not labels:
        labels = ["general_news"] if text_blob else ["unknown"]
        matched_by_label[labels[0]] = []

    primary = next(label for label in PRIMARY_PRIORITY if label in labels)
    return labels, primary, matched_by_label


def normalize_source(author: str, title: str) -> str:
    raw = norm(author)
    joined = f"{raw} {title}"
    if not raw:
        return "unknown"
    for normalized, needles in SOURCE_RULES:
        if any(needle.lower() in joined.lower() for needle in needles):
            return normalized
    if re.search(r"^(Dr\.?\s+\w+|[A-Z][a-z]+ [A-Z][a-z]+)$", raw):
        return "课程原始数据"
    if raw.lower() in {"admin", "test", "tester"}:
        return "课程原始数据"
    return "其他来源"


def quality_bucket(content_len: int) -> str:
    if content_len < 100:
        return "short_content_count"
    if content_len <= 1000:
        return "medium_content_count"
    if content_len <= 5000:
        return "long_content_count"
    return "very_long_content_count"


def counter_rows(counter: Counter[str], total: int, limit: int | None = None) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count, "percentage": pct(count, total)}
        for label, count in counter.most_common(limit)
    ]


def load_supplemental_econ_log() -> dict[str, Any]:
    if not ECON_CLEAN_REPORT.exists():
        return {
            "available": False,
            "clean_report_path": str(ECON_CLEAN_REPORT),
            "index_report_path": str(ECON_INDEX_REPORT),
            "note": "supplemental econ cleaning report not found",
        }

    payload = json.loads(ECON_CLEAN_REPORT.read_text(encoding="utf-8"))
    source_stats = payload.get("source_stats") or {}
    scanned = sum(int(v.get("scanned") or 0) for v in source_stats.values())
    date_window = sum(int(v.get("date_window") or 0) for v in source_stats.values())
    relevant = sum(int(v.get("relevant") or 0) for v in source_stats.values())
    noise_dropped = sum(int(v.get("noise_dropped") or 0) for v in source_stats.values())
    too_short = sum(int(v.get("too_short") or 0) for v in source_stats.values())
    raw_kept = int(payload.get("raw_kept_before_dedupe") or relevant or 0)
    deduped = int(payload.get("deduped_count") or 0)
    duplicates_removed = int((payload.get("dedupe") or {}).get("duplicates_removed") or 0)

    result: dict[str, Any] = {
        "available": True,
        "clean_report_path": str(ECON_CLEAN_REPORT),
        "index_report_path": str(ECON_INDEX_REPORT),
        "as_of": payload.get("as_of"),
        "cutoff": payload.get("cutoff"),
        "scanned_total": scanned,
        "date_window_total": date_window,
        "relevant_before_dedupe": relevant,
        "raw_kept_before_dedupe": raw_kept,
        "deduped_count": deduped,
        "duplicates_removed": duplicates_removed,
        "duplicate_removed_rate_of_kept": pct(duplicates_removed, raw_kept),
        "noise_dropped": noise_dropped,
        "too_short": too_short,
        "source_counts": payload.get("source_counts") or {},
        "recent_windows": payload.get("recent_windows") or {},
    }

    if ECON_INDEX_REPORT.exists():
        index_payload = json.loads(ECON_INDEX_REPORT.read_text(encoding="utf-8"))
        result["index_report"] = {
            "collection": index_payload.get("collection"),
            "doc_count": index_payload.get("doc_count"),
            "qdrant_points_count": index_payload.get("qdrant_points_count"),
            "chunk_type_counts": index_payload.get("chunk_type_counts"),
            "elapsed_seconds": index_payload.get("elapsed_seconds"),
        }
    return result


async def fetch_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    async with AsyncSessionLocal() as db:
        row_result = await db.execute(
            text(
                """
                SELECT
                  n.id, n.title, n.description, n.content, n.author,
                  n.category_id, c.name AS category_name,
                  n.publish_time, n.created_at, n.updated_at
                FROM news n
                LEFT JOIN news_category c ON c.id = n.category_id
                ORDER BY n.id
                """
            )
        )
        rows = [dict(row._mapping) for row in row_result.fetchall()]

        category_result = await db.execute(
            text(
                """
                SELECT c.id AS category_id, c.name AS category, COUNT(n.id) AS count
                FROM news_category c
                LEFT JOIN news n ON n.category_id = c.id
                GROUP BY c.id, c.name
                ORDER BY count DESC, c.id
                """
            )
        )
        categories = [dict(row._mapping) for row in category_result.fetchall()]

        column_result = await db.execute(
            text(
                """
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'news'
                ORDER BY ORDINAL_POSITION
                """
            )
        )
        columns = [dict(row._mapping) for row in column_result.fetchall()]

    return rows, categories, columns


def profile_rows(
    rows: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(rows)
    category_rows = [
        {
            "category_id": row["category_id"],
            "category": row["category"],
            "count": int(row["count"]),
            "percentage": pct(int(row["count"]), total),
        }
        for row in categories
    ]

    multi_counter: Counter[str] = Counter()
    primary_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    quality_counter: Counter[str] = Counter()
    title_counter: Counter[str] = Counter()
    source_primary_matrix: dict[str, Counter[str]] = defaultdict(Counter)
    samples_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    content_lengths: list[int] = []
    empty_title_count = 0
    empty_content_count = 0
    min_publish: datetime | None = None
    max_publish: datetime | None = None

    for row in rows:
        title = norm(row.get("title"))
        content = norm(row.get("content"))
        publish_time = row.get("publish_time")
        content_len = len(content)
        content_lengths.append(content_len)
        if not title:
            empty_title_count += 1
        if not content:
            empty_content_count += 1

        labels, primary, matched_by_label = classify(row)
        for label in labels:
            multi_counter[label] += 1
        primary_counter[primary] += 1

        source = normalize_source(norm(row.get("author")), title)
        source_counter[source] += 1
        source_primary_matrix[source][primary] += 1

        if publish_time:
            year_counter[str(publish_time.year)] += 1
            min_publish = publish_time if min_publish is None or publish_time < min_publish else min_publish
            max_publish = publish_time if max_publish is None or publish_time > max_publish else max_publish

        if title:
            title_counter[title] += 1

        quality_counter[quality_bucket(content_len)] += 1

        if len(samples_by_label[primary]) < 5:
            matched_keywords: list[str] = []
            for label in labels:
                matched_keywords.extend(matched_by_label.get(label, [])[:4])
            samples_by_label[primary].append(
                {
                    "news_id": row.get("id"),
                    "title": title,
                    "category": norm(row.get("category_name")),
                    "source": source,
                    "publish_time": publish_time.isoformat(sep=" ") if publish_time else None,
                    "content_length": content_len,
                    "multi_labels": labels,
                    "matched_keywords": list(dict.fromkeys(matched_keywords))[:12],
                }
            )

    duplicate_title_groups = sum(1 for count in title_counter.values() if count > 1)
    duplicate_title_rows = sum(count for count in title_counter.values() if count > 1)

    recent_windows: dict[str, int] = {}
    for days in [30, 90, 180, 365, 730]:
        cutoff = AS_OF_DATE.toordinal() - days
        recent_windows[f"recent_{days}d"] = sum(
            1
            for row in rows
            if row.get("publish_time") and row["publish_time"].date().toordinal() >= cutoff
        )

    multi_rows = [
        {
            "label": label,
            "matched_count": multi_counter.get(label, 0),
            "matched_percentage_of_total": pct(multi_counter.get(label, 0), total),
        }
        for label in PRIMARY_PRIORITY
        if label in multi_counter
    ]
    primary_rows = [
        {
            "primary_label": label,
            "count": primary_counter.get(label, 0),
            "percentage": pct(primary_counter.get(label, 0), total),
        }
        for label in PRIMARY_PRIORITY
        if primary_counter.get(label, 0)
    ]

    field_mapping = {
        "news_id": "news.id",
        "title": "news.title",
        "description": "news.description",
        "content": "news.content",
        "source": "news.author",
        "category_id": "news.category_id",
        "category_name": "news_category.name",
        "publish_time": "news.publish_time",
        "created_at": "news.created_at",
        "updated_at": "news.updated_at",
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": AS_OF_DATE.isoformat(),
        "scope_guardrails": [
            "read MySQL news/news_category only",
            "read existing econ experiment logs only",
            "did not read or modify Qdrant",
            "did not rebuild indexes",
            "did not change frontend API",
            "did not change Validator enforce config",
        ],
        "data_source": {
            "database": "news_app",
            "primary_parent_table": "news",
            "category_table": "news_category",
            "qdrant_is_excluded_from_parent_count": True,
        },
        "field_mapping": field_mapping,
        "table_columns": columns,
        "raw_clean_counts": {
            "raw_count_from_current_business_table": total,
            "clean_count": total,
            "duplicate_title_groups_in_clean_table": duplicate_title_groups,
            "duplicate_title_rows_in_clean_table": duplicate_title_rows,
            "noise_removed_in_current_business_table": "unknown: no raw import log for current MySQL table",
            "duplicate_removed_before_current_business_table": "unknown: no raw import log for current MySQL table",
        },
        "supplemental_econ_candidate_log": load_supplemental_econ_log(),
        "raw_category_distribution": category_rows,
        "heuristic_multi_label_distribution": multi_rows,
        "heuristic_primary_label_distribution": primary_rows,
        "primary_label_priority": PRIMARY_PRIORITY,
        "source_distribution": counter_rows(source_counter, total),
        "source_primary_matrix": {
            source: counter_rows(counter, sum(counter.values()))
            for source, counter in source_primary_matrix.items()
        },
        "source_normalization_rules": {
            normalized: " OR ".join(needles) for normalized, needles in SOURCE_RULES
        }
        | {
            "课程原始数据": "English personal-name style author, admin/test/tester",
            "其他来源": "non-empty author not matched by known source rules",
            "unknown": "empty author",
        },
        "time_distribution": {
            "min_publish_time": min_publish.isoformat(sep=" ") if min_publish else None,
            "max_publish_time": max_publish.isoformat(sep=" ") if max_publish else None,
            **recent_windows,
            "year_distribution": [
                {"year": year, "count": count, "percentage": pct(count, total)}
                for year, count in sorted(year_counter.items())
            ],
        },
        "content_quality_distribution": {
            "empty_title_count": empty_title_count,
            "empty_content_count": empty_content_count,
            "short_content_count": quality_counter.get("short_content_count", 0),
            "medium_content_count": quality_counter.get("medium_content_count", 0),
            "long_content_count": quality_counter.get("long_content_count", 0),
            "very_long_content_count": quality_counter.get("very_long_content_count", 0),
            "avg_content_length": round(mean(content_lengths), 2) if content_lengths else 0,
            "median_content_length": median(content_lengths) if content_lengths else 0,
            "p90_content_length": percentile(content_lengths, 0.9),
            "max_content_length": max(content_lengths) if content_lengths else 0,
        },
        "samples_by_primary_label": {
            label: samples_by_label.get(label, []) for label in PRIMARY_PRIORITY if samples_by_label.get(label)
        },
        "heuristic_keyword_rules": KEYWORD_RULES,
        "gray_strategy_recommendation": {
            "econ_finance_query": "continue enforce",
            "policy_macro_domain": "shadow only; do not enforce yet",
            "politics_governance_domain": "shadow only; do not enforce yet",
            "other_news_qa": "shadow",
            "general_chat": "do not require evidence",
            "stock_market_related": (
                "allow policy/economy news impact explanation for sectors only; "
                "do not provide individual stock predictions, trading advice, or deterministic investment conclusions"
            ),
        },
        "final_recommendation": (
            "继续经济为主 / 加入政策宏观 shadow / 不建议 policy_macro enforce / 暂不建议股票涨跌预测"
        ),
    }


def keyword_rules_markdown() -> str:
    sections: list[str] = []
    for label in PRIMARY_PRIORITY:
        if label in KEYWORD_RULES:
            sections.append(f"### {label}\n\n```text\n{'、'.join(KEYWORD_RULES[label])}\n```")
    return "\n\n".join(sections)


def build_markdown(profile: dict[str, Any]) -> str:
    total = profile["raw_clean_counts"]["clean_count"]
    category_rows = [
        [row["category_id"], row["category"], row["count"], f"{row['percentage']}%"]
        for row in profile["raw_category_distribution"]
    ]
    multi_rows = [
        [row["label"], row["matched_count"], f"{row['matched_percentage_of_total']}%"]
        for row in profile["heuristic_multi_label_distribution"]
    ]
    primary_rows = [
        [row["primary_label"], row["count"], f"{row['percentage']}%"]
        for row in profile["heuristic_primary_label_distribution"]
    ]
    source_rows = [
        [row["label"], row["count"], f"{row['percentage']}%"]
        for row in profile["source_distribution"]
    ]
    year_rows = [
        [row["year"], row["count"], f"{row['percentage']}%"]
        for row in profile["time_distribution"]["year_distribution"]
    ]
    quality = profile["content_quality_distribution"]
    quality_rows = [
        ["empty_title_count", quality["empty_title_count"]],
        ["empty_content_count", quality["empty_content_count"]],
        ["short_content_count (<100 chars)", quality["short_content_count"]],
        ["medium_content_count (100-1000 chars)", quality["medium_content_count"]],
        ["long_content_count (1000-5000 chars)", quality["long_content_count"]],
        ["very_long_content_count (>5000 chars)", quality["very_long_content_count"]],
        ["avg_content_length", quality["avg_content_length"]],
        ["median_content_length", quality["median_content_length"]],
        ["p90_content_length", quality["p90_content_length"]],
        ["max_content_length", quality["max_content_length"]],
    ]

    supplemental = profile["supplemental_econ_candidate_log"]
    if supplemental.get("available"):
        supplemental_rows = [
            ["clean_report_path", supplemental["clean_report_path"]],
            ["index_report_path", supplemental["index_report_path"]],
            ["scanned_total", supplemental["scanned_total"]],
            ["date_window_total", supplemental["date_window_total"]],
            ["relevant_before_dedupe", supplemental["relevant_before_dedupe"]],
            ["raw_kept_before_dedupe", supplemental["raw_kept_before_dedupe"]],
            ["deduped_count", supplemental["deduped_count"]],
            ["duplicates_removed", supplemental["duplicates_removed"]],
            ["duplicate_removed_rate_of_kept", f"{supplemental['duplicate_removed_rate_of_kept']}%"],
            ["noise_dropped", supplemental["noise_dropped"]],
            ["too_short", supplemental["too_short"]],
        ]
        if supplemental.get("index_report"):
            index_report = supplemental["index_report"]
            supplemental_rows.extend(
                [
                    ["index_collection", index_report.get("collection")],
                    ["index_doc_count", index_report.get("doc_count")],
                    ["qdrant_points_count", index_report.get("qdrant_points_count")],
                    ["index_elapsed_seconds", index_report.get("elapsed_seconds")],
                ]
            )
        supplemental_text = md_table(["metric", "value"], supplemental_rows)
    else:
        supplemental_text = f"_未找到补充经济候选集清洗日志：{supplemental.get('clean_report_path')}_"

    sample_sections: list[str] = []
    for label, samples in profile["samples_by_primary_label"].items():
        rows = [
            [
                item["news_id"],
                truncate(item["title"], 80),
                item["source"],
                item["publish_time"] or "",
                item["content_length"],
                "、".join(item["matched_keywords"]) if item["matched_keywords"] else "",
            ]
            for item in samples
        ]
        sample_sections.append(
            f"### {label}\n\n"
            + md_table(
                ["news_id", "title", "source", "publish_time", "content_length", "matched_keywords"],
                rows,
            )
        )
    samples_markdown = "\n\n".join(sample_sections)

    primary_counts = {
        row["primary_label"]: row["count"] for row in profile["heuristic_primary_label_distribution"]
    }
    econ_count = primary_counts.get("economy_finance", 0)
    policy_count = primary_counts.get("policy_macro", 0)
    politics_count = primary_counts.get("politics_governance", 0)
    stock_count = primary_counts.get("stock_market_related", 0)

    return f"""# News Dataset Profile Report

Generated at: `{profile["generated_at"]}`

## Technical Summary

- 当前业务库 parent 新闻表为 MySQL `news_app.news`，本次画像统计 `clean_count = {total}`。这是站内业务库口径，不是 Qdrant point 数，也不是经济候选 collection 的 19,256 条口径。
- 原始 `category/type` 可用但粒度偏粗，`头条` 占比极高，不能直接支撑细粒度 route/enforce 决策。
- 本报告区分“数据占比高”和“可以 enforce”：占比高只说明值得 shadow 观察；enforce 仍需要灰度指标、引用准确率、拒答质量和稳定性验证。
- 当前结论保持：`econ_finance_query` 继续 enforce；`policy_macro` / `politics_governance` 最多进入 shadow；其他 `news_qa` 继续 shadow；`general_chat` 不强制 evidence。

## 1. 数据源和字段映射

数据源：

```text
database = news_app
primary_parent_table = news
category_table = news_category
```

本报告读取 MySQL parent 新闻表和既有实验日志，不读取 Qdrant。Qdrant 是 chunk/point 级索引，不能代表 parent 新闻数量。

{md_table(["logical_field", "actual_field"], [[k, v] for k, v in profile["field_mapping"].items()])}

## 2. raw / clean 数量

当前生产业务库口径：

{md_table(["metric", "value"], [[k, v] for k, v in profile["raw_clean_counts"].items()])}

补充经济候选集清洗日志口径，不与当前 MySQL `news` 混算：

{supplemental_text}

## 3. 原始 category/type 分布

{md_table(["category_id", "category", "count", "percentage"], category_rows)}

局限：`category_id -> news_category.name` 是前端新闻分类，不是面向 RAG route 的专业标签；`头条` 是宽泛类别，会吞掉经济、政策、产业等更细主题。

## 4. heuristic multi_label 分布

multi_label 允许一条新闻命中多个标签，因此百分比相加可以超过 100%。

{md_table(["label", "matched_count", "matched_percentage_of_total"], multi_rows)}

## 5. heuristic primary_label 分布

primary_label 每条新闻只归入一个主标签，使用“具体标签优先，宽泛标签靠后”的优先级：

```text
{" > ".join(PRIMARY_PRIORITY)}
```

{md_table(["primary_label", "count", "percentage"], primary_rows)}

## 6. 来源分布

source 使用 `news.author` 归一化。

归一化规则：

{md_table(["normalized_source", "rule"], [[k, v] for k, v in profile["source_normalization_rules"].items()])}

分布：

{md_table(["source", "count", "percentage"], source_rows)}

## 7. 时间分布

{md_table(["year", "count", "percentage"], year_rows)}

{md_table(["metric", "value"], [[k, v] for k, v in profile["time_distribution"].items() if k != "year_distribution"])}

如果 source/time 分布偏旧，“最近/最新”类 query 必须继续依赖 time-aware 排序、时间过滤或显式时效提示。

## 8. 内容质量分布

{md_table(["metric", "value"], quality_rows)}

内容长度会影响是否需要 body chunk、父子切分和回答摘要策略。短内容更适合 summary-first；长内容更依赖 body evidence。

## 9. 每类样本

{samples_markdown}

## 10. heuristic 分类关键词规则

{keyword_rules_markdown()}

## 11. 数据画像结论

1. `economy_finance` 当前业务库 primary count = {econ_count}。继续经济 enforce 的依据是前序经济灰度通过，而不是本次画像单独证明。
2. `policy_macro` primary count = {policy_count}，`politics_governance` primary count = {politics_count}。即使占比较高，也只能说明值得进入 shadow 观察，不代表可以直接 enforce。
3. `stock_market_related` primary count = {stock_count}。A 股相关方向当前只能支持“政策/经济新闻对行业或板块的可能影响解释”，不能做个股涨跌预测、买卖建议或确定性投资结论。
4. 当前 MySQL 业务库和经济候选集是两套口径：业务库用于前端新闻/通用站内画像；经济候选集用于 `econ_finance_query` 灰度 RAG。

## 12. 对经济/政策灰度路线的建议

```text
econ_finance_query：继续 enforce
policy_macro / politics_governance：最多建议进入 shadow，不建议直接 enforce
其他 news_qa：继续 shadow
general_chat：不强制 evidence
```

建议逻辑：

- 数据占比高 -> 说明值得进入 shadow 观察。
- 可以 enforce -> 需要通过 Answer Validator shadow 指标、引用准确率、拒答质量、SSE/落库稳定性和灰度测试。
- 经济 enforce 已通过灰度，因此可继续；政策宏观还需要先 shadow 采集失败类型。

## 13. 是否建议新增 policy_macro_query

可以进入需求讨论和 shadow 方案设计，但不建议本阶段直接实现或 enforce。

建议先做：

1. 设计 `policy_macro_query` 的触发词和语句回归测试集。
2. 在 shadow 中记录 citation accuracy、no-answer、wouldRewrite、hallucination_risk。
3. 与 `econ_finance_query` 分开看指标，不混合判断。

## 14. 是否建议进入 A 股板块影响解释模块

暂不建议做个股涨跌预测或投资建议。

可以考虑的边界是：

```text
政策/经济新闻对行业或板块的可能影响解释
```

回答必须使用保守表达：

```text
可能影响
可能利好/利空
仍需结合市场资金、公司基本面和行情数据判断
```

## Final Recommendation

```text
{profile["final_recommendation"]}
```
"""


def write_csv(profile: dict[str, Any], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "label", "count", "percentage", "extra"])
        writer.writeheader()
        for row in profile["raw_category_distribution"]:
            writer.writerow(
                {
                    "section": "raw_category_distribution",
                    "label": row["category"],
                    "count": row["count"],
                    "percentage": row["percentage"],
                    "extra": f"category_id={row['category_id']}",
                }
            )
        for row in profile["heuristic_multi_label_distribution"]:
            writer.writerow(
                {
                    "section": "heuristic_multi_label_distribution",
                    "label": row["label"],
                    "count": row["matched_count"],
                    "percentage": row["matched_percentage_of_total"],
                    "extra": "",
                }
            )
        for row in profile["heuristic_primary_label_distribution"]:
            writer.writerow(
                {
                    "section": "heuristic_primary_label_distribution",
                    "label": row["primary_label"],
                    "count": row["count"],
                    "percentage": row["percentage"],
                    "extra": "",
                }
            )
        for row in profile["source_distribution"]:
            writer.writerow(
                {
                    "section": "source_distribution",
                    "label": row["label"],
                    "count": row["count"],
                    "percentage": row["percentage"],
                    "extra": "",
                }
            )
        for row in profile["time_distribution"]["year_distribution"]:
            writer.writerow(
                {
                    "section": "year_distribution",
                    "label": row["year"],
                    "count": row["count"],
                    "percentage": row["percentage"],
                    "extra": "",
                }
            )
        for key, value in profile["content_quality_distribution"].items():
            writer.writerow(
                {
                    "section": "content_quality_distribution",
                    "label": key,
                    "count": value,
                    "percentage": "",
                    "extra": "",
                }
            )
        for label, samples in profile["samples_by_primary_label"].items():
            for item in samples:
                writer.writerow(
                    {
                        "section": "sample",
                        "label": label,
                        "count": item["news_id"],
                        "percentage": "",
                        "extra": json.dumps(item, ensure_ascii=False),
                    }
                )


async def run(doc_path: Path, json_path: Path, csv_path: Path) -> dict[str, Any]:
    try:
        rows, categories, columns = await fetch_rows()
        profile = profile_rows(rows, categories, columns)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        write_csv(profile, csv_path)
        doc_path.write_text(build_markdown(profile), encoding="utf-8")
        return {
            "clean_count": profile["raw_clean_counts"]["clean_count"],
            "markdown": str(doc_path),
            "json": str(json_path),
            "csv": str(csv_path),
            "final_recommendation": profile["final_recommendation"],
        }
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile the current MySQL parent news dataset.")
    parser.add_argument("--json", default=str(DEFAULT_JSON_PATH), help="Output JSON path.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="Output CSV path.")
    parser.add_argument("--md", default=str(DEFAULT_DOC_PATH), help="Output Markdown path.")
    args = parser.parse_args()

    result = asyncio.run(run(Path(args.md), Path(args.json), Path(args.csv)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
