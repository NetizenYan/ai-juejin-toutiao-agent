"""Compare v1/v2 retrieval eval reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLDS = {
    "RouteAccuracy": 0.94,
    "Recall@5": 0.65,
    "EvidenceRecall@5": 0.55,
    "LatencyP95": 1200.0,
}


def _metric(payload: dict[str, Any], name: str) -> float | None:
    metrics = payload.get("metrics") if "metrics" in payload else payload
    value = metrics.get(name) if isinstance(metrics, dict) else None
    if value is None:
        return None
    return float(value)


def compare_metric_sets(
    v1_metrics: dict[str, Any],
    v2_metrics: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    failed: list[str] = []
    deltas: dict[str, float | None] = {}
    values: dict[str, dict[str, float | None]] = {}
    for name, threshold in thresholds.items():
        v1 = _metric(v1_metrics, name)
        v2 = _metric(v2_metrics, name)
        values[name] = {"v1": v1, "v2": v2, "threshold": threshold}
        deltas[name] = None if v1 is None or v2 is None else round(v2 - v1, 6)
        if v2 is None:
            failed.append(name)
            continue
        if name == "LatencyP95":
            if v2 > threshold:
                failed.append(name)
            continue
        if v2 < threshold:
            failed.append(name)

    return {
        "ready_for_gray": not failed,
        "failed_gates": failed,
        "thresholds": thresholds,
        "values": values,
        "deltas": deltas,
    }


def load_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_markdown(result: dict[str, Any], *, v1_path: str, v2_path: str) -> str:
    lines = [
        "# Context RAG v1/v2 A/B Compare",
        "",
        f"- v1 report: `{v1_path}`",
        f"- v2 report: `{v2_path}`",
        f"- Ready for gray: `{str(result['ready_for_gray']).lower()}`",
        "",
        "| Metric | v1 | v2 | Delta | Gate |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, values in result["values"].items():
        failed = name in result["failed_gates"]
        lines.append(
            "| {name} | {v1} | {v2} | {delta} | {gate} |".format(
                name=name,
                v1=values.get("v1"),
                v2=values.get("v2"),
                delta=result["deltas"].get(name),
                gate="fail" if failed else "pass",
            )
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare v1 and v2 eval JSON reports.")
    parser.add_argument("--v1-json", required=True)
    parser.add_argument("--v2-json", required=True)
    parser.add_argument("--output", default="", help="Path for markdown output (alias for --out-md)")
    parser.add_argument("--out-json", default="eval/reports/context_rag_ab_compare_20260622.json")
    parser.add_argument("--out-md", default="eval/reports/context_rag_ab_compare_20260622.md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = compare_metric_sets(load_report(args.v1_json), load_report(args.v2_json))
    out_json = Path(args.out_json)
    out_md = Path(args.output) if args.output else Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(result, v1_path=args.v1_json, v2_path=args.v2_json), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
