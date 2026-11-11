"""Compare a candidate judge's verdicts with a reference judge on the same turns.
usage: judge_calib.py <reference_dir> <candidate_dir>"""
import json, glob, sys, collections
ref_dir, cand_dir = sys.argv[1], sys.argv[2]
def rows(d, pat):
    out = {}
    for f in sorted(glob.glob(f"{d}/{pat}")):
        for n, l in enumerate(open(f, encoding="utf-8"), 1):
            try: x = json.loads(l)
            except Exception: print("  bad json", f, n); continue
            out[x.get("key")] = x
    return out
T = rows(cand_dir, "turns_*.jsonl"); R = rows(ref_dir, "verdicts_*.jsonl"); C = rows(cand_dir, "verdicts_*.jsonl")
print(f"format: turns {len(T)} candidate {len(C)} missing {len(set(T)-set(C))} extra {len(set(C)-set(T))}")
bad = [k for k, v in C.items() if v.get("verdict") not in ("pass", "partial", "fail")]
print("invalid verdict values:", len(bad))
reasons = collections.Counter(v.get("reason") for v in C.values())
print(f"distinct reasons {len(reasons)} / {len(C)}; most common: {reasons.most_common(3)}")
keys = [k for k in T if k in C and k in R]
dist = lambda D: collections.Counter(D[k]["verdict"] for k in keys)
print("reference:", dict(dist(R)), " candidate:", dict(dist(C)))
agree = sum(R[k]["verdict"] == C[k]["verdict"] for k in keys) / len(keys)
# pass vs not-pass kappa
a = [R[k]["verdict"] != "pass" for k in keys]; b = [C[k]["verdict"] != "pass" for k in keys]
po = sum(x == y for x, y in zip(a, b)) / len(keys)
pa, pb = sum(a) / len(keys), sum(b) / len(keys)
pe = pa * pb + (1 - pa) * (1 - pb)
kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
print(f"exact agreement {agree:.1%}; pass/not-pass agreement {po:.1%}, kappa {kappa:.2f}")
conf = collections.Counter((R[k]["verdict"], C[k]["verdict"]) for k in keys)
print("confusion (reference -> candidate):", dict(sorted(conf.items())))
for side, D in (("reference", R), ("candidate", C)):
    print(f"{side} fabrication: {sum(bool(D[k].get('fabrication')) for k in keys)}")
anchors = [k for k in keys if T[k].get("turn_type") == "carrier" and "站内未找到可靠新闻证据" in T[k]["answer"]]
print("anchor (news question answered 站内未找到):", [(k, C[k]["verdict"]) for k in anchors])
for k, side in [(k, "") for k in keys if R[k]["verdict"] != C[k]["verdict"]]:
    pass
dis = [k for k in keys if R[k]["verdict"] != C[k]["verdict"]]
json.dump([{"key": k, "turn_type": T[k].get("turn_type"), "user": T[k]["user"], "answer": T[k]["answer"],
            "expected": T[k].get("expected_behavior"), "ref": [R[k]["verdict"], R[k]["reason"]],
            "cand": [C[k]["verdict"], C[k]["reason"]]} for k in dis],
          open(f"{cand_dir}/../calib_disagreements_{cand_dir.rstrip('/').split('/')[-1]}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("disagreements:", len(dis), "(written for review)")
