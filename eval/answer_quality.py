"""Answer-quality grading for full-e2e results.

The context-RAG eval checks retrieval, citations and refusals, but not whether the answer is
useful. This module builds one grading packet per answer (question, answer, cited evidence
text), grades it with a judge model or reads grades produced elsewhere (a person or another
model), and summarizes them.

    # 1. packets from a full-e2e report
    python -m eval.answer_quality packets --report reports/eval_R4_expanded115.json \
        --out reports/aq_packets_R4.jsonl
    # 2a. grade with an OpenAI-compatible judge (JUDGE_API_BASE / JUDGE_API_KEY / JUDGE_MODEL)
    python -m eval.answer_quality judge --packets reports/aq_packets_R4.jsonl --out reports/aq_scores_R4.jsonl
    # 2b. or write scores by hand / by another model in the same JSONL schema
    # 3. summary
    python -m eval.answer_quality summarize --packets reports/aq_packets_R4.jsonl \
        --scores reports/aq_scores_R4.jsonl --report reports/aq_R4.md

Score schema (one JSON object per line):
    {"id": ..., "relevance": 0-2, "faithfulness": 0-2, "completeness": 0-2, "constraints": 0-2,
     "usefulness": 1-5, "flags": ["template", "unsupported_claim", "off_topic", "over_refusal"],
     "comment": "...", "grader": "..."}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "processed" / "econ_corpus_20250610_20260610.jsonl"
CITATION_RE = re.compile(r"\[(news:[A-Za-z0-9:_\-]+)\]")
EVIDENCE_CHARS = 700
DIMENSIONS = ("relevance", "faithfulness", "completeness", "constraints")
FLAGS = ("template", "unsupported_claim", "off_topic", "over_refusal")
TEMPLATE_PREFIXES = ("近期相关报道主要聚焦", "仅凭新闻报道不能判断涨跌或收益，以下", "近期有相关报道")

RUBRIC = """你是新闻问答系统的评审。只依据给出的引用证据判断，不要用你自己的知识补充。
对回答按下面四项各打 0/1/2 分：
- relevance 切题：2=直接回答了用户这一轮实际问的问题；1=沾边但没回答到点上（如只罗列标题）；0=答非所问。
- faithfulness 忠实：2=每个实质说法都能在所引证据里找到；1=有个别说法证据里找不到或夸大；0=主要说法没有证据支持或与证据矛盾。
  拒答且确实无证据时给 2。
- completeness 完整：2=覆盖了问题需要的要点（多文档题要综合多篇）；1=只覆盖一部分；0=几乎没有实质内容。
- constraints 约束：2=遵守了用户提出的字数、简短、带引用、保守表达等要求，投资类问题没有确定性判断；1=部分违反；0=明显违反。
再给 usefulness 总体有用度 1-5（5=用户拿到就能用；3=有点用但要追问；1=没用）。
证据里确实没有能回答问题的内容时，明确说明未找到的正确拒答算有用，usefulness 给 4；证据里有答案却拒答，给 over_refusal 并按没用处理。
数字、名称要核对是否挂在了证据里的正确对象上（例如 A 赛事的门票收入不能写成 B 赛事的）。
flags 从 template（只是标题罗列的模板回答）、unsupported_claim、off_topic、over_refusal（有可用证据却拒答）中选，可为空。
只输出一行 JSON：{"relevance":..,"faithfulness":..,"completeness":..,"constraints":..,"usefulness":..,"flags":[..],"comment":"一句话理由"}"""


def is_template_answer(answer: str) -> bool:
    return str(answer or "").lstrip().startswith(TEMPLATE_PREFIXES)


def _clip(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[:limit] + "…"


def load_corpus_index(path: Path | None) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    if not path or not path.exists():
        return index
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            index[row["evidence_id"]] = {
                "title": row.get("title") or "",
                "date": str(row.get("publish_time") or "")[:10],
                "source": row.get("source") or "",
                "text": row.get("content") or row.get("summary") or "",
            }
    return index


async def load_mysql_news(ids: set[int]) -> dict[str, dict[str, str]]:
    """news:<int> evidence (新闻联播 and other station news) lives in MySQL."""
    if not ids:
        return {}
    from sqlalchemy import bindparam, text

    from config.db_conf import AsyncSessionLocal, async_engine

    stmt = text("SELECT id, title, content, publish_time FROM news WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(stmt, {"ids": sorted(ids)})).all()
    finally:
        await async_engine.dispose()
    return {
        f"news:{row.id}": {
            "title": row.title or "",
            "date": str(row.publish_time or "")[:10],
            "source": "station",
            "text": row.content or "",
        }
        for row in rows
    }


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text or "")
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def best_window(text: str, answer: str, size: int = EVIDENCE_CHARS) -> str:
    """The stretch of a long document that best matches the answer.

    A 新闻联播 "article" is a whole day's transcript; the cited story is often deep inside it, so
    grading against the first characters makes correct citations look unsupported.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= size:
        return value
    target = _bigrams(answer)
    best_start, best_score = 0, -1
    for start in range(0, len(value) - size + 1, size // 4):
        score = len(_bigrams(value[start:start + size]) & target)
        if score > best_score:
            best_start, best_score = start, score
    prefix = "…" if best_start else ""
    return prefix + value[best_start:best_start + size] + "…"


def _turns(row: dict[str, Any]) -> list[str]:
    turns = row.get("turns")
    if isinstance(turns, list) and turns:
        return [str(turn if isinstance(turn, str) else turn.get("question") or turn.get("content") or "") for turn in turns]
    return [str(row.get("question") or "")]


def build_packets(rows: list[dict[str, Any]], evidence: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    packets = []
    for row in rows:
        answer = str(row.get("answer") or "")
        cited = list(dict.fromkeys(CITATION_RE.findall(answer)))
        packets.append({
            "id": row["id"],
            "case_type": row.get("case_type"),
            "should_answer": row.get("should_answer"),
            "turns": _turns(row),
            "answer": answer,
            "is_template": is_template_answer(answer),
            "trace_stages": [step.get("stage") for step in ((row.get("done") or {}).get("validationTrace") or [])],
            "cited": [
                {"ref": ref, **{k: (best_window(v, answer) if k == "text" else v)
                                for k, v in evidence.get(ref, {"title": "", "date": "", "source": "", "text": "(未找到证据原文)"}).items()}}
                for ref in cited
            ],
        })
    return packets


def judge_prompt(packet: dict[str, Any]) -> str:
    lines = ["对话（最后一轮是要回答的问题）："]
    lines += [f"用户第{i + 1}轮：{turn}" for i, turn in enumerate(packet["turns"])]
    lines += ["", f"系统回答：{packet['answer']}", "", "所引证据："]
    if not packet["cited"]:
        lines.append("（无引用）")
    for item in packet["cited"]:
        lines.append(f"[{item['ref']}] {item.get('date', '')}《{item.get('title', '')}》{item.get('text', '')}")
    return "\n".join(lines)


def parse_judgment(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    for key in DIMENSIONS:
        if not isinstance(data.get(key), int) or not 0 <= data[key] <= 2:
            return None
    if not isinstance(data.get("usefulness"), int) or not 1 <= data["usefulness"] <= 5:
        return None
    data["flags"] = [flag for flag in data.get("flags") or [] if flag in FLAGS]
    return data


async def judge_packets(packets: list[dict[str, Any]], *, base_url: str, api_key: str, model: str,
                        concurrency: int = 4) -> list[dict[str, Any]]:
    import httpx

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def judge_one(client: Any, packet: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                response = await client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "temperature": 0,
                        "messages": [{"role": "system", "content": RUBRIC}, {"role": "user", "content": judge_prompt(packet)}],
                    },
                )
                response.raise_for_status()
                body = response.json()
            except Exception as exc:  # noqa: BLE001 - one failed call must not lose the other grades
                return {"id": packet["id"], "grader": model, "error": type(exc).__name__}
        content = body["choices"][0]["message"]["content"] or ""
        parsed = parse_judgment(content)
        return {"id": packet["id"], "grader": model, "usage": body.get("usage"),
                **(parsed or {"error": "unparseable", "raw": content[:500]})}

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=300) as client:
        return list(await asyncio.gather(*(judge_one(client, packet) for packet in packets)))


def summarize(packets: list[dict[str, Any]], scores: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {packet["id"]: packet for packet in packets}
    valid = [score for score in scores if score.get("id") in by_id and "usefulness" in score]

    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"n": 0}
        result: dict[str, Any] = {"n": len(items)}
        for key in DIMENSIONS:
            result[key] = round(statistics.mean(item[key] for item in items), 3)
        result["usefulness"] = round(statistics.mean(item["usefulness"] for item in items), 3)
        result["useful_rate"] = round(sum(item["usefulness"] >= 4 for item in items) / len(items), 3)
        result["flags"] = dict(Counter(flag for item in items for flag in item.get("flags") or []))
        return result

    by_type: dict[str, list] = defaultdict(list)
    for score in valid:
        by_type[str(by_id[score["id"]].get("case_type"))].append(score)
    return {
        "overall": block(valid),
        "template": block([s for s in valid if by_id[s["id"]]["is_template"]]),
        "non_template": block([s for s in valid if not by_id[s["id"]]["is_template"]]),
        "by_case_type": {key: block(value) for key, value in sorted(by_type.items())},
        "graders": dict(Counter(score.get("grader") for score in valid)),
        "missing": sorted(set(by_id) - {score["id"] for score in valid}),
    }


def agreement(scores_a: list[dict[str, Any]], scores_b: list[dict[str, Any]]) -> dict[str, Any]:
    """How far two graders agree on the same answers (e.g. Claude vs another judge model)."""
    a = {s["id"]: s for s in scores_a if "usefulness" in s}
    b = {s["id"]: s for s in scores_b if "usefulness" in s}
    ids = sorted(set(a) & set(b))
    if not ids:
        return {"n": 0}
    ua, ub = [a[i]["usefulness"] for i in ids], [b[i]["usefulness"] for i in ids]
    useful_a, useful_b = [u >= 4 for u in ua], [u >= 4 for u in ub]
    observed = sum(x == y for x, y in zip(useful_a, useful_b)) / len(ids)
    pa, pb = sum(useful_a) / len(ids), sum(useful_b) / len(ids)
    expected = pa * pb + (1 - pa) * (1 - pb)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": len(ids),
        "usefulness_mean_a": round(statistics.mean(ua), 3),
        "usefulness_mean_b": round(statistics.mean(ub), 3),
        "useful_rate_a": round(pa, 3),
        "useful_rate_b": round(pb, 3),
        "usefulness_exact": round(sum(x == y for x, y in zip(ua, ub)) / len(ids), 3),
        "usefulness_within_1": round(sum(abs(x - y) <= 1 for x, y in zip(ua, ub)) / len(ids), 3),
        "useful_agreement": round(observed, 3),
        "useful_kappa": round(kappa, 3),
        "dimension_mean_diff_b_minus_a": {
            key: round(statistics.mean(b[i][key] - a[i][key] for i in ids), 3) for key in DIMENSIONS
        },
        "large_disagreements": [
            {"id": i, "a": a[i]["usefulness"], "b": b[i]["usefulness"],
             "a_comment": a[i].get("comment"), "b_comment": b[i].get("comment")}
            for i in ids if abs(a[i]["usefulness"] - b[i]["usefulness"]) >= 2
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    header = "| 范围 | 题数 | 切题 | 忠实 | 完整 | 约束 | 有用度(1-5) | 有用率(≥4) |"
    lines = ["# 回答质量评分", "", f"评分者：{summary['graders']}", "", header, "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]

    def row(name: str, block: dict[str, Any]) -> str:
        if not block.get("n"):
            return f"| {name} | 0 | | | | | | |"
        return (f"| {name} | {block['n']} | {block['relevance']} | {block['faithfulness']} | {block['completeness']} | "
                f"{block['constraints']} | {block['usefulness']} | {block['useful_rate']:.0%} |")

    lines.append(row("全部", summary["overall"]))
    lines.append(row("模板兜底", summary["template"]))
    lines.append(row("非模板", summary["non_template"]))
    for key, block in summary["by_case_type"].items():
        lines.append(row(key, block))
    lines += ["", f"问题标记：{summary['overall'].get('flags', {})}"]
    if summary["missing"]:
        lines += ["", f"未评分：{', '.join(summary['missing'])}"]
    lines += ["", "四项各 0-2 分，有用度 1-5。各维度定义见 eval/answer_quality.py 的 RUBRIC。"]
    return "\n".join(lines) + "\n"


def human_sheet(packets: list[dict[str, Any]], sample_size: int, seed: int) -> str:
    rng = random.Random(seed)
    chosen = rng.sample(packets, min(sample_size, len(packets)))
    lines = ["# 回答质量人工评分表", "",
             "每题填四项 0/1/2 和有用度 1-5（评分标准见文末）。填完后告诉我，我用它校准模型评分。", ""]
    for packet in chosen:
        lines.append(f"## {packet['id']}（{packet['case_type']}）")
        lines += [f"- 用户第{i + 1}轮：{turn}" for i, turn in enumerate(packet["turns"])]
        lines.append("")
        lines.append(f"**系统回答**：{packet['answer']}")
        lines.append("")
        for item in packet["cited"]:
            lines.append(f"> [{item['ref']}] {item.get('date', '')}《{item.get('title', '')}》{_clip(item.get('text'), 300)}")
        lines += ["", "切题：__ 忠实：__ 完整：__ 约束：__ 有用度：__ 备注：", ""]
    lines += ["---", "", "## 评分标准", "", RUBRIC]
    return "\n".join(lines) + "\n"


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


async def _packets_command(args: argparse.Namespace) -> None:
    rows = json.loads(Path(args.report).read_text(encoding="utf-8"))["rows"]
    evidence = load_corpus_index(Path(args.corpus))
    cited = {ref for row in rows for ref in CITATION_RE.findall(str(row.get("answer") or ""))}
    station_ids = {int(ref.split(":")[1]) for ref in cited if re.fullmatch(r"news:\d+", ref)}
    evidence.update(await load_mysql_news(station_ids))
    packets = build_packets(rows, evidence)
    _write_jsonl(args.out, packets)
    if args.human_sheet:
        Path(args.human_sheet).write_text(human_sheet(packets, args.human_sample, args.seed), encoding="utf-8")
    print(f"{len(packets)} packets -> {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("packets")
    p.add_argument("--report", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    p.add_argument("--human-sheet", default="")
    p.add_argument("--human-sample", type=int, default=20)
    p.add_argument("--seed", type=int, default=20261023)
    j = sub.add_parser("judge")
    j.add_argument("--packets", required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--concurrency", type=int, default=4)
    s = sub.add_parser("summarize")
    s.add_argument("--packets", required=True)
    s.add_argument("--scores", required=True, nargs="+")
    s.add_argument("--report", default="")
    c = sub.add_parser("compare")
    c.add_argument("--a", required=True, nargs="+", help="score files of grader A")
    c.add_argument("--b", required=True, nargs="+", help="score files of grader B")
    args = parser.parse_args()

    if args.command == "packets":
        asyncio.run(_packets_command(args))
    elif args.command == "judge":
        base_url, api_key, model = (os.getenv("JUDGE_API_BASE"), os.getenv("JUDGE_API_KEY"), os.getenv("JUDGE_MODEL"))
        if not (base_url and api_key and model):
            raise SystemExit("set JUDGE_API_BASE, JUDGE_API_KEY and JUDGE_MODEL")
        scores = asyncio.run(judge_packets(_read_jsonl(args.packets), base_url=base_url, api_key=api_key, model=model,
                                           concurrency=args.concurrency))
        _write_jsonl(args.out, scores)
        print(f"{len(scores)} scores -> {args.out}")
    elif args.command == "compare":
        result = agreement([r for p in args.a for r in _read_jsonl(p)], [r for p in args.b for r in _read_jsonl(p)])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        scores = [row for path in args.scores for row in _read_jsonl(path)]
        summary = summarize(_read_jsonl(args.packets), scores)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.report:
            Path(args.report).write_text(render_markdown(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
