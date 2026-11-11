import json, glob, subprocess, sys, collections
sys.path.insert(0, ".")
from harness import rule_requests as NEW
src = subprocess.run(["git", "show", "HEAD:harness/rule_requests.py"], capture_output=True, text=True).stdout
OLD = type(sys)("old_rr"); exec(src, OLD.__dict__)
msgs = set()
for f in glob.glob("eval/gold/*.jsonl"):
    for line in open(f):
        try: r = json.loads(line)
        except Exception: continue
        for k in ("question", "query", "user"):
            if isinstance(r.get(k), str): msgs.add(r[k])
        for t in r.get("turns") or []:
            if isinstance(t, dict) and isinstance(t.get("user"), str): msgs.add(t["user"])
        for st in r.get("steps") or []:
            if isinstance(st, str): msgs.add(st)
ans = []
for d in sorted(glob.glob("../../codex_qgen/judge_*")):
    V = {}
    for f in glob.glob(f"{d}/verdicts_*.jsonl"):
        for l in open(f):
            try: x = json.loads(l); V[x["key"]] = x
            except Exception: pass
    for f in glob.glob(f"{d}/turns_*.jsonl"):
        for l in open(f):
            t = json.loads(l)
            q = t.get("question") or t.get("user") or ""
            if isinstance(q, str): msgs.add(q)
            ans.append((d.split("/")[-1], t["key"], t.get("answer") or "", V.get(t["key"], {}).get("verdict")))
ch = [(OLD.classify(m), NEW.classify(m), m) for m in msgs if OLD.classify(m) != NEW.classify(m)]
print(len(msgs), "messages; classify changed", len(ch))
for o, n, m in ch: print(f"  {o}->{n} | {m[:100]}")
flips = [(d, k, v, a[:80].replace("\n", " ")) for d, k, a, v in ans if NEW.agrees_to_rule_change(a) and not OLD.agrees_to_rule_change(a)]
print(len(ans), "answers; newly 'agrees'", len(flips))
for f in flips: print("  ", f)
# Workaround detector: answers whose removed paragraphs changed.
wch = [(d, k, v, a) for d, k, a, v in ans if NEW.without_citation_workarounds(a)[1] and not OLD.without_citation_workarounds(a)[1]]
seen = set(); uniq = [w for w in wch if not (w[3] in seen or seen.add(w[3]))]
print(len(ans), "answers; newly 'workaround'", len(wch), "unique", len(uniq), collections.Counter(w[2] for w in uniq))
for d, k, v, a in uniq:
    removed = [p for p in a.split("\n\n") if p not in NEW.without_citation_workarounds(a)[0]]
    print("  ", d, k, v, "|", " / ".join(p.replace("\n", " ")[:120] for p in removed))
