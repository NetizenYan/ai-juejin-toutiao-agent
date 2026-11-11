# Reviewed Label Coverage

This report is read-only. It projects coverage if accepted reviewed-label rows are promoted.

## Summary

- Formal gold count: 50
- Reviewed-label rows: 80
- Accepted rows: 65
- Merge rows: 15
- Needs evidence lookup: 0
- Rejected rows: 0
- Projected formal count after accepts: 115
- Target total: 100

## Class Projection

| Case type | Formal | Accepted | Merged | Projected formal | Remaining deficit |
| --- | ---: | ---: | ---: | ---: | ---: |
| `A_exact_news_qa` | 6 | 14 | 1 | 20 | 0 |
| `B_context_follow_up` | 6 | 14 | 6 | 20 | 0 |
| `C_time_sensitive` | 6 | 9 | 2 | 15 | 0 |
| `D_source_limited` | 7 | 8 | 1 | 15 | 0 |
| `E_multi_document` | 7 | 8 | 3 | 15 | 0 |
| `F_similar_distractor` | 6 | 4 | 1 | 10 | 0 |
| `G_no_answer` | 6 | 4 | 1 | 10 | 0 |
| `H_investment_boundary` | 6 | 4 | 0 | 10 | 0 |

## Blockers

- None for reviewed-label coverage. Formal promotion, split creation, and baselines are still separate gates.

## Guardrails

- This report does not modify formal gold.
- Merge rows do not count as new coverage.
- Do not use draft labels as held-out cases before manual confirmation.
- Do not run automatic tuning until the tuning gate checker returns `ok=true`.
