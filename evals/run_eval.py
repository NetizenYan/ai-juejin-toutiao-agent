"""Eval Set 跑分：对 /api/ai/chat 跑 qa_set.jsonl，校验意图行为是否符合预期。

判据（MVP）：
- expect_evidence=true（news_qa/recommendation）：本轮应命中证据（evidence 非空）→ 说明确实经 MCP 工具取数。
- expect_evidence=false（general_chat）：不应调任何涉库工具（evidence 为空）。

用法（项目根目录，需后端已在 --base 端口运行）：
    <agent-python> -m evals.run_eval --base http://127.0.0.1:8020 --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _register(base: str) -> str:
    body = json.dumps({"username": f"eval_{int(time.time())}", "password": "secret123"}).encode()
    req = urllib.request.Request(base + "/api/user/register", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["data"]["token"]


def _chat(base: str, token: str, message: str) -> tuple[str, list]:
    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(base + "/api/ai/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    answer, evidence = "", []
    with urllib.request.urlopen(req, timeout=240) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            if "delta" in obj:
                answer += obj["delta"]
            elif obj.get("event") == "done":
                evidence = obj.get("evidence") or []
            elif obj.get("event") == "error":
                answer = "[ERROR] " + str(obj.get("detail"))
    return answer, evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8020")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    args = parser.parse_args()

    cases = []
    with open(os.path.join(HERE, "qa_set.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    if args.limit:
        cases = cases[: args.limit]

    token = _register(args.base)
    passed = 0
    print(f"== Eval: {len(cases)} 条 ==")
    for case in cases:
        t0 = time.time()
        answer, evidence = _chat(args.base, token, case["q"])
        has_ev = len(evidence) > 0
        reasons = []

        # 1) 证据行为：该调工具/不该调
        if has_ev != case["expect_evidence"]:
            reasons.append("evidence" + ("应空" if not case["expect_evidence"] else "应非空"))

        # 2) 相关性：证据是否命中期望的 news_id（任一即可）
        refs_any = case.get("expect_refs_any")
        if refs_any and not (set(evidence) & set(refs_any)):
            reasons.append(f"未命中期望ref{refs_any}")

        # 3) 答案是否在点上（含任一关键词）
        contains_any = case.get("expect_answer_contains_any")
        if contains_any and not any(kw.lower() in answer.lower() for kw in contains_any):
            reasons.append(f"答案缺关键词{contains_any}")

        ok = not reasons
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} ({case['intent']}, {time.time()-t0:.1f}s) "
              f"ev={evidence if evidence else '∅'}"
              + ("" if ok else " | 失败:" + ";".join(reasons))
              + f" | {answer[:40].replace(chr(10), ' ')}")
    print(f"\nSCORE: {passed}/{len(cases)} ({100*passed//max(len(cases),1)}%)")


if __name__ == "__main__":
    main()
