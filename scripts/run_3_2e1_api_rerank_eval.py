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
REPORT_DIR = PROJECT_ROOT / "eval" / "reports" / "3_2E_1"
EXPANDED_GOLD = PROJECT_ROOT / "eval" / "gold" / "eval_gold_retrieval_expanded115_20260623.jsonl"
ORIGINAL_GOLD = PROJECT_ROOT / "eval" / "gold" / "eval_gold_retrieval.jsonl"
TRAIN_SPLIT = PROJECT_ROOT / "eval" / "gold" / "splits" / "retrieval_train_202606.jsonl"
HELDOUT_SPLIT = PROJECT_ROOT / "eval" / "gold" / "splits" / "retrieval_heldout_202606.jsonl"

MODEL = os.getenv("RERANKER_API_MODEL", "Pro/BAAI/bge-reranker-v2-m3")
DOCUMENT_MAX_CHARS = os.getenv("RERANKER_API_DOCUMENT_MAX_CHARS", "1600")


def _run_eval(name: str, collection: str, gold: Path) -> dict[str, str]:
    prefix = REPORT_DIR / name
    env = os.environ.copy()
    env["QDRANT_UNIFIED_COLLECTION"] = collection
    env["RERANKER_API_MODEL"] = MODEL
    env["RERANKER_API_DOCUMENT_MAX_CHARS"] = DOCUMENT_MAX_CHARS
    print(f"START {name} collection={collection} gold={gold.name}", flush=True)
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "eval.eval_context_rag",
        "--gold",
        str(gold),
        "--mode",
        "retrieve-only",
        "--use-v2",
        "--api-rerank",
        "--api-rerank-model",
        MODEL,
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
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)
    print(f"DONE {name}", flush=True)
    return {
        "name": name,
        "collection": collection,
        "gold": str(gold.relative_to(PROJECT_ROOT)),
        "report": str(prefix.with_suffix(".md").relative_to(PROJECT_ROOT)),
        "json_report": str(prefix.with_suffix(".json").relative_to(PROJECT_ROOT)),
        "diagnosis_report": str(prefix.with_name(prefix.name + "_diag.md").relative_to(PROJECT_ROOT)),
        "failure_report": str(prefix.with_name(prefix.name + "_failure.md").relative_to(PROJECT_ROOT)),
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            ids.add(str(json.loads(raw)["id"]))
    return ids


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


def _metric_row(dataset: str, collection: str, rows: list[dict[str, Any]], json_report: str) -> dict[str, Any]:
    from eval.eval_context_rag import compute_metrics

    metrics = compute_metrics(rows, top_k=5)
    return {
        "dataset": dataset,
        "collection": collection,
        "cases": metrics["cases"],
        "answerable_gold_cases": metrics["answerable_gold_cases"],
        "recall_at_5": metrics["Recall@5"],
        "evidence_recall_at_5": metrics["EvidenceRecall@5"],
        "mrr": metrics["MRR"],
        "route_accuracy": metrics["RouteAccuracy"],
        "latency_p50_ms": metrics["LatencyP50"],
        "latency_p95_ms": metrics["LatencyP95"],
        "json_report": json_report,
        **_api_meta(rows),
    }


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.2f}%"


def _ms(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.2f} ms"


def _write_summary(runs: list[dict[str, str]]) -> None:
    train_ids = _load_ids(TRAIN_SPLIT)
    heldout_ids = _load_ids(HELDOUT_SPLIT)
    metric_rows: list[dict[str, Any]] = []

    for run in runs:
        payload = _load_json(PROJECT_ROOT / run["json_report"])
        rows = payload.get("rows") or []
        if "expanded115" in run["name"]:
            metric_rows.append(_metric_row("expanded115", run["collection"], rows, run["json_report"]))
            train_rows = [row for row in rows if str(row.get("id")) in train_ids]
            heldout_rows = [row for row in rows if str(row.get("id")) in heldout_ids]
            metric_rows.append(_metric_row("train80", run["collection"], train_rows, run["json_report"]))
            metric_rows.append(_metric_row("heldout35", run["collection"], heldout_rows, run["json_report"]))
        else:
            metric_rows.append(_metric_row("original50", run["collection"], rows, run["json_report"]))

    summary = {
        "stage": "3.2E.1_api_reranker_experiment",
        "reranker_model": MODEL,
        "runs": runs,
        "metrics": metric_rows,
    }
    summary_json = REPORT_DIR / "3_2E_1_API_RERANK_SUMMARY_20260623.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 3.2E.1 API Reranker Experiment - 2026-06-23",
        "",
        "## Scope",
        "",
        f"- Reranker API model: `{MODEL}`",
        "- Reranker endpoint: SiliconFlow `/v1/rerank`",
        f"- Max rerank document text: `{DOCUMENT_MAX_CHARS}` chars per candidate",
        "- Mode: retrieve-only, top_k=20, metric_k=5, limit=50",
        "- No embedding, chunk, index, Qdrant rebuild, or production RAG default changes.",
        "- API key was read from process environment only and was not written to reports.",
        "",
        "## Metrics",
        "",
        "| Dataset | Collection | Cases | Recall@5 | EvidenceRecall@5 | MRR | RouteAccuracy | Eval P95 | API Used | API Failed | API P95 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metric_rows:
        lines.append(
            "| "
            f"{row['dataset']} | {row['collection']} | {row['cases']} | "
            f"{_pct(row['recall_at_5'])} | {_pct(row['evidence_recall_at_5'])} | {_pct(row['mrr'])} | "
            f"{_pct(row['route_accuracy'])} | {_ms(row['latency_p95_ms'])} | "
            f"{row['api_used_cases']} | {row['api_failed_cases']} | {_ms(row['api_latency_p95_ms'])} |"
        )
    lines.extend([
        "",
        "## Reports",
        "",
    ])
    for run in runs:
        lines.append(f"- `{run['name']}`: `{run['report']}`, `{run['json_report']}`, `{run['failure_report']}`")
    lines.append("")
    summary_md = REPORT_DIR / "3_2E_1_API_RERANK_SUMMARY_20260623.md"
    summary_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not os.getenv("SILICONFLOW_API_KEY") and not os.getenv("RERANKER_API_KEY"):
        raise SystemExit("SILICONFLOW_API_KEY or RERANKER_API_KEY is required")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    runs = [
        _run_eval("expanded115_current_news_chunks_v2_api_rerank", "news_chunks_v2", EXPANDED_GOLD),
        _run_eval(
            "expanded115_v32e_api_bge_m3_test_api_rerank",
            "news_chunks_v32e_api_bge_m3_test",
            EXPANDED_GOLD,
        ),
        _run_eval(
            "original50_no_algorithm_api_bge_m3_test_api_rerank",
            "news_chunks_v32e_api_bge_m3_test",
            ORIGINAL_GOLD,
        ),
    ]
    _write_summary(runs)
    print(str((REPORT_DIR / "3_2E_1_API_RERANK_SUMMARY_20260623.md").relative_to(PROJECT_ROOT)))


if __name__ == "__main__":
    main()
