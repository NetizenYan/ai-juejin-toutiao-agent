"""Retrieval evaluation for the unified news Agent RAG path.

The script compares the cautious production options:

- summary-only
- global body_fallback_slots=1
- query_router_v1

Metrics are computed at parent news-id level while evidence metrics look at the
returned chunks/body evidence. This keeps the eval aligned with parent-child RAG.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select

from config.db_conf import AsyncSessionLocal, async_engine
from harness.rag_search import search_news_rag
from harness.reranker import rerank
from models.news import News


CASES: list[tuple[str, list[str]]] = [
    ("央行有没有降准放水", ["降准"]),
    ("人工智能和芯片的新进展", ["AI芯片", "芯片"]),
    ("博鳌论坛今年办了吗", ["博鳌"]),
    ("我国互联网域名数量", ["域名"]),
    ("GDP经济增长数据", ["GDP"]),
    ("OpenAI发布了什么模型", ["OpenAI", "GPT"]),
    ("英伟达的AI硬件", ["英伟达"]),
    ("中国女足的比赛", ["女足"]),
    ("费德勒退役", ["费德勒"]),
    ("C罗转会去哪", ["C罗"]),
    ("超级计算机与算力", ["超算", "超级计算"]),
    ("特斯拉的芯片", ["特斯拉"]),
    ("美联储加息", ["美联储", "加息"]),
    ("数字经济发展", ["数字经济"]),
    ("乡村振兴战略", ["乡村振兴"]),
    ("碳市场和碳价", ["碳市场", "碳价"]),
    ("外汇储备变化", ["外汇储备"]),
    ("促进消费的政策", ["消费促进", "促进消费"]),
    ("跨境电商出口", ["跨境电商"]),
    ("量子计算突破", ["量子"]),
    ("全球通胀情况", ["通胀", "物价", "CPI"]),
    ("A股市场行情", ["A股", "股市", "股指"]),
    ("房地产楼市政策", ["房地产", "楼市", "房价"]),
    ("新能源汽车销量", ["新能源", "电动车", "新能源汽车"]),
    ("光伏与太阳能", ["光伏", "太阳能"]),
    ("半导体产业", ["半导体"]),
    ("5G网络建设", ["5G"]),
    ("机器人技术", ["机器人"]),
    ("比特币与加密货币", ["比特币", "加密货币", "数字货币"]),
    ("元宇宙概念", ["元宇宙"]),
    ("区块链应用", ["区块链"]),
    ("人民币汇率", ["人民币", "汇率"]),
    ("制造业景气PMI", ["制造业", "PMI"]),
    ("就业与失业率", ["就业", "失业"]),
    ("减税降费政策", ["减税", "降费"]),
    ("一带一路倡议", ["一带一路"]),
    ("进博会广交会", ["进博会", "广交会"]),
    ("碳中和双碳目标", ["碳中和", "双碳"]),
    ("脱贫攻坚成果", ["脱贫", "扶贫"]),
    ("两会人大政协", ["两会", "人大", "政协"]),
    ("习近平重要讲话", ["习近平"]),
    ("国务院常务会议", ["国务院"]),
    ("疫情防控", ["疫情", "防控", "新冠"]),
    ("奥运会赛事", ["奥运"]),
    ("世界杯足球", ["世界杯"]),
    ("诺贝尔奖", ["诺贝尔"]),
    ("高考相关", ["高考"]),
    ("台风地震灾害", ["台风", "地震", "暴雨"]),
]

HARD_CASES: list[dict[str, Any]] = [
    {
        "query": "新闻联播最近提到人工智能的具体内容有哪些",
        "keywords": ["人工智能", "智能"],
        "notes": "source + content detail query",
    },
    {
        "query": "GDP数据里提到哪些具体变化",
        "keywords": ["GDP", "经济"],
        "notes": "content/data query",
    },
    {
        "query": "最近新能源汽车政策有什么进展",
        "keywords": ["新能源", "汽车"],
        "notes": "timeline/recent query",
    },
]


@dataclass(frozen=True)
class RetrievalStrategy:
    name: str
    query_router_enabled: bool
    chunk_type_filter: str | None
    body_fallback_slots: int
    notes: str


STRATEGY_MAP = {
    "summary-only": RetrievalStrategy(
        name="summary-only",
        query_router_enabled=False,
        chunk_type_filter="summary",
        body_fallback_slots=0,
        notes="summary filter, no body fallback",
    ),
    "global body_fallback_slots=1": RetrievalStrategy(
        name="global body_fallback_slots=1",
        query_router_enabled=False,
        chunk_type_filter="summary",
        body_fallback_slots=1,
        notes="global body fallback ablation",
    ),
    "query_router_v1": RetrievalStrategy(
        name="query_router_v1",
        query_router_enabled=True,
        chunk_type_filter="summary",
        body_fallback_slots=0,
        notes="router controls when body fallback is allowed",
    ),
}

DEFAULT_STRATEGIES = "summary-only,global body_fallback_slots=1,query_router_v1"


def parse_strategies(value: str) -> list[RetrievalStrategy]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    strategies: list[RetrievalStrategy] = []
    for name in names:
        if name not in STRATEGY_MAP:
            raise ValueError(f"unsupported strategy: {name}")
        strategies.append(STRATEGY_MAP[name])
    return strategies


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", default=DEFAULT_STRATEGIES)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--include-hard-cases", action="store_true")
    parser.add_argument("--only-hard-cases", action="store_true")
    return parser.parse_args(argv)


def _item_parent_id(item: dict[str, Any]) -> int | None:
    try:
        return int(item.get("parent_news_id") or item.get("id"))
    except (TypeError, ValueError):
        return None


def item_ids(items: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for item in items:
        parent_id = _item_parent_id(item)
        if parent_id is None or parent_id in seen:
            continue
        seen.add(parent_id)
        ids.append(parent_id)
    return ids


def retrieval_metrics(ranked_ids: list[int], gold: set[int], k: int) -> dict[str, float | int]:
    topk = ranked_ids[:k]
    hit = 1 if set(topk) & gold else 0
    rr = 0.0
    for index, news_id in enumerate(ranked_ids, 1):
        if news_id in gold:
            rr = 1.0 / index
            break
    recall = len(set(topk) & gold) / min(len(gold), k) if gold else 0.0
    return {"hit": hit, "mrr": rr, "recall": recall}


def evidence_recall_metrics(items: list[dict[str, Any]], keywords: list[str], k: int) -> dict[str, int]:
    topk = items[:k]
    hit = 1 if any(
        any(keyword in str(item.get("summary") or item.get("text") or item.get("title") or "") for keyword in keywords)
        for item in topk
    ) else 0
    return {"evidence_hit": hit}


def body_evidence_metrics(ranked_ids: list[int], body_evidence: list[dict[str, Any]], k: int) -> dict[str, float | int]:
    topk = ranked_ids[:k]
    if not topk:
        return {"body_evidence_count": 0, "body_evidence_coverage": 0.0}
    evidence_parent_ids = set(item_ids(body_evidence))
    covered = len(set(topk) & evidence_parent_ids)
    return {
        "body_evidence_count": covered,
        "body_evidence_coverage": covered / len(topk),
    }


async def _gold_ids(db, keywords: list[str]) -> set[int]:
    conditions = [News.title.like(f"%{keyword}%") for keyword in keywords]
    rows = (await db.execute(select(News.id).where(or_(*conditions)))).all()
    return {int(row.id) for row in rows}


def _case_rows(include_hard_cases: bool, only_hard_cases: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not only_hard_cases:
        rows.extend({"query": query, "keywords": keywords, "notes": "48-case retrieval eval"} for query, keywords in CASES)
    if include_hard_cases or only_hard_cases:
        rows.extend(HARD_CASES)
    return rows


async def evaluate_strategy(
    strategy: RetrievalStrategy,
    *,
    top_k: int = 5,
    candidate_limit: int = 50,
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    eval_cases = cases or _case_rows(include_hard_cases=False, only_hard_cases=False)
    totals = {
        "hit": 0.0,
        "mrr": 0.0,
        "recall": 0.0,
        "evidence_hit": 0.0,
        "body_evidence_coverage": 0.0,
        "latency_ms": 0.0,
    }
    evaluated = 0
    skipped = 0
    rows: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        for case in eval_cases:
            keywords = list(case.get("keywords") or [])
            gold = set(case.get("gold_ids") or [])
            if not gold and keywords:
                gold = await _gold_ids(db, keywords)
            if not gold:
                skipped += 1
                continue

            start = time.perf_counter()
            rag_result = await search_news_rag(
                case["query"],
                limit=candidate_limit,
                ranking="hybrid",
                chunk_type_filter=strategy.chunk_type_filter,
                expand_body_evidence=True,
                body_chunks_per_parent=1,
                body_fallback_slots=strategy.body_fallback_slots,
                query_router_enabled=strategy.query_router_enabled,
            )
            items = rag_result.get("items") or []
            ranked_items = await rerank(case["query"], items, top_k=max(top_k, min(len(items), 25)))
            latency_ms = (time.perf_counter() - start) * 1000
            ranked_ids = item_ids(ranked_items)
            retrieval = retrieval_metrics(ranked_ids, gold, top_k)
            evidence = evidence_recall_metrics(ranked_items, keywords, top_k)
            body = body_evidence_metrics(ranked_ids, rag_result.get("body_evidence") or [], top_k)

            totals["hit"] += float(retrieval["hit"])
            totals["mrr"] += float(retrieval["mrr"])
            totals["recall"] += float(retrieval["recall"])
            totals["evidence_hit"] += float(evidence["evidence_hit"])
            totals["body_evidence_coverage"] += float(body["body_evidence_coverage"])
            totals["latency_ms"] += latency_ms
            evaluated += 1
            rows.append({
                "query": case["query"],
                "gold_ids": sorted(gold),
                "hit_ids": ranked_ids[:top_k],
                "rag_route": rag_result.get("rag_route"),
                "latency_ms": round(latency_ms, 2),
            })

    denominator = max(1, evaluated)
    return {
        "strategy": strategy.name,
        "cases": evaluated,
        "skipped": skipped,
        "hit_at_k": totals["hit"] / denominator,
        "mrr": totals["mrr"] / denominator,
        "recall_at_k": totals["recall"] / denominator,
        "evidence_recall_at_k": totals["evidence_hit"] / denominator,
        "body_evidence_at_k": totals["body_evidence_coverage"] / denominator,
        "latency_ms": totals["latency_ms"] / denominator,
        "notes": strategy.notes,
        "rows": rows,
    }


async def evaluate_collection(
    strategies: list[RetrievalStrategy],
    *,
    top_k: int = 5,
    candidate_limit: int = 50,
    include_hard_cases: bool = False,
    only_hard_cases: bool = False,
) -> list[dict[str, Any]]:
    cases = _case_rows(include_hard_cases=include_hard_cases, only_hard_cases=only_hard_cases)
    reports: list[dict[str, Any]] = []
    for strategy in strategies:
        reports.append(
            await evaluate_strategy(
                strategy,
                top_k=top_k,
                candidate_limit=candidate_limit,
                cases=cases,
            )
        )
    return reports


def _pct(value: float) -> str:
    return f"{value:.0%}"


def format_strategy_table(reports: list[dict[str, Any]]) -> str:
    lines = [
        "| Strategy | Hit@5 | MRR | Recall@5 | EvidenceRecall@5 | BodyEvidence@5 | Latency | Notes |",
        "| -------- | ----: | --: | -------: | ---------------: | -------------: | ------: | ----- |",
    ]
    for report in reports:
        lines.append(
            "| {strategy} | {hit} | {mrr:.3f} | {recall} | {evidence} | {body} | {latency:.0f}ms | {notes} |".format(
                strategy=report["strategy"],
                hit=_pct(float(report["hit_at_k"])),
                mrr=float(report["mrr"]),
                recall=_pct(float(report["recall_at_k"])),
                evidence=_pct(float(report["evidence_recall_at_k"])),
                body=_pct(float(report["body_evidence_at_k"])),
                latency=float(report["latency_ms"]),
                notes=report.get("notes") or "",
            )
        )
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    try:
        reports = await evaluate_collection(
            parse_strategies(args.strategies),
            top_k=args.top_k,
            candidate_limit=args.candidate_limit,
            include_hard_cases=args.include_hard_cases,
            only_hard_cases=args.only_hard_cases,
        )
        print(format_strategy_table(reports))
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
