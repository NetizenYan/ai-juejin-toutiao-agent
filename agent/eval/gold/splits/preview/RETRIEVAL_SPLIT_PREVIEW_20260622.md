# Retrieval Split Preview

## Preview Only

This split is generated from a preview gold file. It must not be used as the official tuning split.

## Summary

- Input cases: 115
- Train cases: 80
- Held-out cases: 35
- Held-out ratio: 0.3
- Minimum held-out target: 30
- Seed: `20260622`
- Overlap count: 0
- Evidence groups: 48
- Evidence group overlap: 0

## Class Counts

| Case type | Total | Train | Held-out |
| --- | ---: | ---: | ---: |
| `A_exact_news_qa` | 20 | 14 | 6 |
| `B_context_follow_up` | 20 | 14 | 6 |
| `C_time_sensitive` | 15 | 10 | 5 |
| `D_source_limited` | 15 | 10 | 5 |
| `E_multi_document` | 15 | 10 | 5 |
| `F_similar_distractor` | 10 | 8 | 2 |
| `G_no_answer` | 10 | 7 | 3 |
| `H_investment_boundary` | 10 | 7 | 3 |

## Guardrails

- Do not use this preview split for automatic tuning decisions.
- Do not create official split files until reviewed labels are confirmed.
- Keep the tuning gate closed until train and held-out 3.2E baselines exist.
