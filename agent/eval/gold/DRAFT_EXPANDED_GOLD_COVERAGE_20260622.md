# 3.3 Gold Expansion Coverage

## Summary

- Formal gold count: 115
- Candidate count: 0
- Target total: 100-150
- Need 0 more formal cases to reach 100 total.
- Need 0 more reviewed/accepted cases to reach 100 total.

## Class Coverage

| Case type | Formal | Candidates | Projected if all accepted | Formal deficit | Projected deficit |
| --- | ---: | ---: | ---: | ---: | ---: |
| `A_exact_news_qa` | 20 | 0 | 20 | 0 | 0 |
| `B_context_follow_up` | 20 | 0 | 20 | 0 | 0 |
| `C_time_sensitive` | 15 | 0 | 15 | 0 | 0 |
| `D_source_limited` | 15 | 0 | 15 | 0 | 0 |
| `E_multi_document` | 15 | 0 | 15 | 0 | 0 |
| `F_similar_distractor` | 10 | 0 | 10 | 0 | 0 |
| `G_no_answer` | 10 | 0 | 10 | 0 | 0 |
| `H_investment_boundary` | 10 | 0 | 10 | 0 | 0 |

## Candidate Gaps

- No case type has both zero candidates and a remaining formal coverage deficit.

## Guardrails

- This report is read-only.
- Do not tune weights from this candidate set.
- Do not promote candidates into formal gold before reviewed-label validation.
- Do not create `scripts/tune_rag_weights.py` before the documented gate is met.
