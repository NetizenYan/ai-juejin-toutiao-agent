# 3.3 Tuning Gate Check - 2026-06-23

## Result

| Item | Value |
|---|---:|
| ok | true |
| formal_count | 115 |
| train_count | 80 |
| heldout_count | 35 |
| blocker_count | 0 |

## Inputs

- Coverage: `eval/gold/GOLD_EXPANSION_COVERAGE_EXPANDED115_20260623.json`
- Train split: `eval/gold/splits/retrieval_train_202606.jsonl`
- Held-out split: `eval/gold/splits/retrieval_heldout_202606.jsonl`
- Train baseline report: `eval/reports/3_3/train80_baseline_3_2E_current.json`
- Held-out baseline report: `eval/reports/3_3/heldout35_baseline_3_2E_current.json`

## Decision

The gate is open for a future tuning phase, but this run did not start automatic tuning.

No `tune_rag_weights.py` was created, and no retrieval code was modified.
