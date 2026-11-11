# Reviewed Labels Draft

This is a draft review aid, not the formal reviewed-label file.

## Summary

- Draft rows: 80
- Suggested accepts: 65
- Suggested merges: 15
- Needs evidence lookup: 0
- Suggested rejects: 0

## By Case Type

| Case type | Draft rows |
| --- | ---: |
| `A_exact_news_qa` | 15 |
| `B_context_follow_up` | 20 |
| `C_time_sensitive` | 11 |
| `D_source_limited` | 9 |
| `E_multi_document` | 11 |
| `F_similar_distractor` | 5 |
| `G_no_answer` | 5 |
| `H_investment_boundary` | 4 |

## Guardrails

- Do not copy this draft wholesale into formal gold.
- Review every `accept_as_gold` row before writing it to `reviewed_labels_20260622.jsonl`.
- Treat `merge_with_existing` rows as non-new coverage unless a reviewer rewrites them.
- Do not use this draft for tuning or held-out split creation.
