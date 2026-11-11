# Judge tooling

Scripts used with an independent LLM judge (Codex, prompt `PROMPT_JUDGE_v2.2.md`) on `eval.drift_eval` runs.
Compare scores only between runs judged by the same judge with the same prompt; two runs of the same code
differ by 3–5 points per 150 turns, so judge a full run before reading a change into the numbers.

| Script | Use |
|---|---|
| `export_turns.py <results.jsonl> <attack seeds> <out dir> [carriers]` | Writes `turns_NN.jsonl` (150 turns each) for the judge. Run with `PYTHONPATH=.` |
| `compare_judges.py <reference dir> <candidate dir>` | Agreement and kappa between two sets of `verdicts_NN.jsonl` on the same turns |
| `rule_regression.py` | Replays `rule_requests` over every judged user message and answer, against `git HEAD`: what the working tree classifies differently |
| `replay_request_reply.py <results.jsonl> '<judge dir>/turns_*.jsonl' <old agent.py>` | Replays the draft-acceptance step (`agent._request_reply`) on a finished run, old code against new, without calling the model |

The judge directories (`judge_<run>/turns_NN.jsonl`, `verdicts_NN.jsonl`) live outside the repository; the
scripts take their paths as arguments or read `../../codex_qgen` by default.
