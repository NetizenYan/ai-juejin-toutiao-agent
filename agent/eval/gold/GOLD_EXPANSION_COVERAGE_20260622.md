# 3.3 Gold Expansion Coverage

## Summary

- Formal gold count: 50
- Candidate count: 80
- Target total: 100-150
- Need 50 more formal cases to reach 100 total.
- Need 0 more reviewed/accepted cases to reach 100 total.

## Class Coverage

| Case type | Formal | Candidates | Projected if all accepted | Formal deficit | Projected deficit |
| --- | ---: | ---: | ---: | ---: | ---: |
| `A_exact_news_qa` | 6 | 15 | 21 | 14 | 0 |
| `B_context_follow_up` | 6 | 20 | 26 | 14 | 0 |
| `C_time_sensitive` | 6 | 11 | 17 | 9 | 0 |
| `D_source_limited` | 7 | 9 | 16 | 8 | 0 |
| `E_multi_document` | 7 | 11 | 18 | 8 | 0 |
| `F_similar_distractor` | 6 | 5 | 11 | 4 | 0 |
| `G_no_answer` | 6 | 5 | 11 | 4 | 0 |
| `H_investment_boundary` | 6 | 4 | 10 | 4 | 0 |

## Candidate Gaps

- No case type has both zero candidates and a remaining formal coverage deficit.

## Guardrails

- This report is read-only.
- Do not tune weights from this candidate set.
- Do not promote candidates into formal gold before reviewed-label validation.
- Do not create `scripts/tune_rag_weights.py` before the documented gate is met.
