"""Export the EXT3 attack run for an independent judge, in the EXT2 turns_NN.jsonl format."""
import json, sys
from pathlib import Path
from agent.eval import drift_eval

results_path, seeds_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
carrier_path = Path(sys.argv[4]) if len(sys.argv) > 4 else drift_eval.CARRIER_SOURCE
out_dir.mkdir(parents=True, exist_ok=True)
carriers = {c["question"]: c for c in drift_eval._load(carrier_path)}
items = {it["id"]: it for it in drift_eval.load_items("attacks", seeds_path, carrier_path)}
rows = []
for line in results_path.read_text().splitlines():
    result = json.loads(line)
    item = items[result["id"]]
    answers = {r["turn"]: r for r in result["records"]}
    users: list[str] = []
    for turn in item["turns"]:
        record = answers.get(turn["turn"], {})
        carrier = carriers.get(turn["user"]) if turn["turn_type"] == "carrier" else None
        rows.append({
            "key": f"{item['id']}#{turn['turn']}",
            "kind": "attack",
            "turn_type": turn["turn_type"],
            "attack_tactic": turn.get("attack_tactic"),
            "expected_behavior": turn["expected_behavior"],
            "success_signal": item.get("success_signal") if turn["turn_type"] == "attack" else None,
            "previous_user_messages": users[-6:],
            "user": turn["user"],
            "answer": record.get("answer", ""),
            "answer_points": (carrier or {}).get("answer_points"),
            "reference_answer": (carrier or {}).get("reference_answer"),
        })
        users.append(turn["user"])
for n in range(0, len(rows), 150):
    path = out_dir / f"turns_{n // 150 + 1:02d}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[n:n + 150]))
print(len(rows), "turns in", (len(rows) + 149) // 150, "files")
