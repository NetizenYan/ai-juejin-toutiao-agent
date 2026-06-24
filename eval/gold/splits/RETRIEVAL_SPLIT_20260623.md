# Retrieval Split 20260623

## 3.3 Expanded Gold Baseline

This split is generated from the applied reviewed labels and the expanded 115-case formal gold file.

## Summary

- Input cases: 115
- Train cases: 80
- Held-out cases: 35
- Held-out ratio: 0.3
- Minimum held-out target: 30
- Seed: `20260623`
- Overlap count: 0
- Evidence groups: 48
- Evidence group overlap: 0

## Class Counts

| Case type | Total | Train | Held-out |
| --- | ---: | ---: | ---: |
| `A_exact_news_qa` | 20 | 14 | 6 |
| `B_context_follow_up` | 20 | 13 | 7 |
| `C_time_sensitive` | 15 | 10 | 5 |
| `D_source_limited` | 15 | 10 | 5 |
| `E_multi_document` | 15 | 11 | 4 |
| `F_similar_distractor` | 10 | 8 | 2 |
| `G_no_answer` | 10 | 7 | 3 |
| `H_investment_boundary` | 10 | 7 | 3 |

## Guardrails

- Use this split for 3.3 baseline measurement.
- Do not run automatic tuning unless the tuning gate checker returns `ok=true`.
- Do not create or run `scripts/tune_rag_weights.py` in this baseline pass.
