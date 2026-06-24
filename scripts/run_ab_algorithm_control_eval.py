from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=False)

REPORT_DIR = PROJECT_ROOT / "eval" / "reports" / "3_2E_1" / "ab_algorithm_control_20260623"
EXPANDED_GOLD = PROJECT_ROOT / "eval" / "gold" / "eval_gold_retrieval_expanded115_20260623.jsonl"
TRAIN_SPLIT = PROJECT_ROOT / "eval" / "gold" / "splits" / "retrieval_train_202606.jsonl"
HELDOUT_SPLIT = PROJECT_ROOT / "eval" / "gold" / "splits" / "retrieval_heldout_202606.jsonl"

RERANKER_MODEL = os.getenv("RERANKER_API_MODEL", "Pro/BAAI/bge-reranker-v2-m3")


RUNS = [
    {
        "name": "A0_news_chunks_v2_control_no_api_rerank",
        "label": "A0",
        "version": "A",
        "collection": "news_chunks_v2",
        "algorithm": "control_no_external_reranker",
        "api_rerank": False,
    },
    {
        "name": "A1_news_chunks_v2_api_rerank",
        "label": "A1",
        "version": "A",
        "collection": "news_chunks_v2",
        "algorithm": "api_reranker",
        "api_rerank": True,
    },
    {
        "name": "C0_api_bge_control_no_api_rerank",
        "label": "C0",
        "version": "C_control_for_B",
        "collection": "news_chunks_v32e_api_bge_m3_test",
        "algorithm": "control_no_external_reranker",
        "api_rerank": False,
    },
    {
        "name": "B1_api_bge_api_rerank",
        "label": "B1",
        "version": "B",
        "collection": "news_chunks_v32e_api_bge_m3_test",
        "algorithm": "api_reranker",
        "api_rerank": True,
    },
]


def _load_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                ids.add(str(json.loads(raw)["id"]))
    return ids


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _api_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metas = [row.get("reranker_meta") or {} for row in rows]
    used = [m for m in metas if m.get("used")]
    failed = [m for m in metas if m and not m.get("used")]
    latencies = sorted(float(m.get("latency_ms") or 0.0) for m in used)

    def percentile(p: float) -> float | None:
        if not latencies:
            return None
        if len(latencies) == 1:
            return latencies[0]
        rank = (len(latencies) - 1) * p
        lower = int(rank)
        upper = min(lower + 1, len(latencies) - 1)
        weight = rank - lower
        return round(latencies[lower] * (1 - weight) + latencies[upper] * weight, 2)

    return {
        "api_used_cases": len(used),
        "api_failed_cases": len(failed),
        "api_latency_p50_ms": percentile(0.50),
        "api_latency_p95_ms": percentile(0.95),
    }


def _metric_row(dataset: str, run: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    from eval.eval_context_rag import compute_metrics

    metrics = compute_metrics(rows, top_k=5)
    return {
        "dataset": dataset,
        "label": run["label"],
        "version": run["version"],
        "collection": run["collection"],
        "algorithm": run["algorithm"],
        "cases": metrics["cases"],
        "answerable_gold_cases": metrics["answerable_gold_cases"],
        "recall_at_5": metrics["Recall@5"],
        "evidence_recall_at_5": metrics["EvidenceRecall@5"],
        "mrr": metrics["MRR"],
        "route_accuracy": metrics["RouteAccuracy"],
        "latency_p50_ms": metrics["LatencyP50"],
        "latency_p95_ms": metrics["LatencyP95"],
        **_api_meta(rows),
    }


def _run_eval(run: dict[str, Any]) -> dict[str, Any]:
    prefix = REPORT_DIR / run["name"]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["QDRANT_UNIFIED_COLLECTION"] = run["collection"]
    env["EMBEDDING_MODEL"] = "Pro/BAAI/bge-m3"
    env["EMBEDDING_V2_MODEL"] = "Pro/BAAI/bge-m3"
    env["RERANKER_API_MODEL"] = RERANKER_MODEL

    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "eval.eval_context_rag",
        "--gold",
        str(EXPANDED_GOLD),
        "--mode",
        "retrieve-only",
        "--use-v2",
        "--top-k",
        "20",
        "--metric-k",
        "5",
        "--limit",
        "50",
        "--report",
        str(prefix.with_suffix(".md")),
        "--json-report",
        str(prefix.with_suffix(".json")),
        "--diagnosis-report",
        str(prefix.with_name(prefix.name + "_diag.md")),
        "--diagnosis-json",
        str(prefix.with_name(prefix.name + "_diag.json")),
        "--failure-report",
        str(prefix.with_name(prefix.name + "_failure.md")),
    ]

    if run["api_rerank"]:
        env["RERANKER_PROVIDER"] = "api"
        command.extend(["--api-rerank", "--api-rerank-model", RERANKER_MODEL])
    else:
        env["RERANKER_PROVIDER"] = "off"
        env["RERANKER_API_ENABLED"] = "0"

    print(f"START {run['label']} {run['name']} collection={run['collection']} algorithm={run['algorithm']}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)
    print(f"DONE {run['label']} {run['name']}", flush=True)

    return {
        **run,
        "gold": str(EXPANDED_GOLD.relative_to(PROJECT_ROOT)),
        "report": str(prefix.with_suffix(".md").relative_to(PROJECT_ROOT)),
        "json_report": str(prefix.with_suffix(".json").relative_to(PROJECT_ROOT)),
        "diagnosis_report": str(prefix.with_name(prefix.name + "_diag.md").relative_to(PROJECT_ROOT)),
        "failure_report": str(prefix.with_name(prefix.name + "_failure.md").relative_to(PROJECT_ROOT)),
    }


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.2f}%"


def _ms(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.2f} ms"


def _delta(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return float(new) - float(old)


def _write_summary(runs: list[dict[str, Any]]) -> None:
    train_ids = _load_ids(TRAIN_SPLIT)
    heldout_ids = _load_ids(HELDOUT_SPLIT)
    metric_rows: list[dict[str, Any]] = []

    rows_by_label: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        payload = _load_json(PROJECT_ROOT / run["json_report"])
        rows = payload.get("rows") or []
        rows_by_label[run["label"]] = rows
        metric_rows.append(_metric_row("expanded115", run, rows))
        metric_rows.append(_metric_row("train80", run, [row for row in rows if str(row.get("id")) in train_ids]))
        metric_rows.append(_metric_row("heldout35", run, [row for row in rows if str(row.get("id")) in heldout_ids]))

    expanded_by_label = {row["label"]: row for row in metric_rows if row["dataset"] == "expanded115"}
    comparisons = [
        {
            "name": "A 算法增益",
            "from": "A0",
            "to": "A1",
            "recall_delta": _delta(expanded_by_label["A1"]["recall_at_5"], expanded_by_label["A0"]["recall_at_5"]),
            "evidence_delta": _delta(expanded_by_label["A1"]["evidence_recall_at_5"], expanded_by_label["A0"]["evidence_recall_at_5"]),
            "mrr_delta": _delta(expanded_by_label["A1"]["mrr"], expanded_by_label["A0"]["mrr"]),
        },
        {
            "name": "B 算法增益，以 C0 为对照",
            "from": "C0",
            "to": "B1",
            "recall_delta": _delta(expanded_by_label["B1"]["recall_at_5"], expanded_by_label["C0"]["recall_at_5"]),
            "evidence_delta": _delta(expanded_by_label["B1"]["evidence_recall_at_5"], expanded_by_label["C0"]["evidence_recall_at_5"]),
            "mrr_delta": _delta(expanded_by_label["B1"]["mrr"], expanded_by_label["C0"]["mrr"]),
        },
        {
            "name": "C 数据底座相对 A 数据底座",
            "from": "A0",
            "to": "C0",
            "recall_delta": _delta(expanded_by_label["C0"]["recall_at_5"], expanded_by_label["A0"]["recall_at_5"]),
            "evidence_delta": _delta(expanded_by_label["C0"]["evidence_recall_at_5"], expanded_by_label["A0"]["evidence_recall_at_5"]),
            "mrr_delta": _delta(expanded_by_label["C0"]["mrr"], expanded_by_label["A0"]["mrr"]),
        },
    ]

    summary = {
        "stage": "ab_algorithm_control_20260623",
        "gold": str(EXPANDED_GOLD.relative_to(PROJECT_ROOT)),
        "reranker_model": RERANKER_MODEL,
        "common_embedding_model": "Pro/BAAI/bge-m3",
        "runs": runs,
        "metrics": metric_rows,
        "comparisons": comparisons,
    }
    summary_json = REPORT_DIR / "AB_ALGORITHM_CONTROL_SUMMARY_20260623.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AB 算法对照评测 - 2026-06-23",
        "",
        "## 实验口径",
        "",
        "- 数据集：`expanded115`。",
        "- 模式：`retrieve-only`，只测召回，不测生成。",
        "- 公共 embedding：SiliconFlow `Pro/BAAI/bge-m3`。",
        f"- API reranker：SiliconFlow `{RERANKER_MODEL}`。",
        "- A0/C0：关闭外部 reranker，保留 v2 检索内部的 query intent、三路召回和 light_rerank_v2。",
        "- A1/B1：在同样 v2 检索基础上增加 API reranker。",
        "- C0 是 B1 的对照组：同 collection，同 PG/Qdrant 数据底座，只差外部 reranker。",
        "",
        "## 指标",
        "",
        "| Dataset | Label | Version | Collection | Algorithm | Cases | Recall@5 | EvidenceRecall@5 | MRR | RouteAccuracy | P95 | API Used | API Failed | API P95 |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metric_rows:
        lines.append(
            "| "
            f"{row['dataset']} | {row['label']} | {row['version']} | `{row['collection']}` | {row['algorithm']} | "
            f"{row['cases']} | {_pct(row['recall_at_5'])} | {_pct(row['evidence_recall_at_5'])} | "
            f"{_pct(row['mrr'])} | {_pct(row['route_accuracy'])} | {_ms(row['latency_p95_ms'])} | "
            f"{row['api_used_cases']} | {row['api_failed_cases']} | {_ms(row['api_latency_p95_ms'])} |"
        )

    lines.extend([
        "",
        "## expanded115 对比结论",
        "",
        "| 对比 | 从 | 到 | Recall@5 变化 | EvidenceRecall@5 变化 | MRR 变化 |",
        "|---|---|---|---:|---:|---:|",
    ])
    for item in comparisons:
        lines.append(
            "| "
            f"{item['name']} | {item['from']} | {item['to']} | "
            f"{_pct(item['recall_delta'])} | {_pct(item['evidence_delta'])} | {_pct(item['mrr_delta'])} |"
        )

    lines.extend([
        "",
        "## 报告文件",
        "",
    ])
    for run in runs:
        lines.append(f"- {run['label']}: `{run['report']}`, `{run['json_report']}`, `{run['failure_report']}`")
    lines.append("")

    summary_md = REPORT_DIR / "AB_ALGORITHM_CONTROL_SUMMARY_20260623.md"
    summary_md.write_text("\n".join(lines), encoding="utf-8")
    print(str(summary_md.relative_to(PROJECT_ROOT)))


def main() -> None:
    if not os.getenv("EMBEDDING_API_KEY") and not os.getenv("SILICONFLOW_API_KEY"):
        raise SystemExit("EMBEDDING_API_KEY or SILICONFLOW_API_KEY is required")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    finished = [_run_eval(run) for run in RUNS]
    _write_summary(finished)


if __name__ == "__main__":
    main()
