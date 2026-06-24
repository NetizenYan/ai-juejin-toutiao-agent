# Reviewed Label Promotion Audit

This report is read-only. It does not modify formal gold, official labels, or split files.

## Decision

- Formal promotion ready: `true`

## Official Reviewed Labels

- Rows: 80
- Accepted: 65
- Rejected: 0
- Projected formal count: 115
- Validation OK: `true`

## Draft Reviewed Labels

- Rows: 80
- Accepted: 65
- Rejected: 0
- Projected formal count: 115
- Validation OK: `true`

## Blockers

- None for formal reviewed-label promotion.

## Warnings

- None.

## Official Class Projection

| Case type | Projected formal | Remaining deficit |
| --- | ---: | ---: |
| `A_exact_news_qa` | 20 | 0 |
| `B_context_follow_up` | 20 | 0 |
| `C_time_sensitive` | 15 | 0 |
| `D_source_limited` | 15 | 0 |
| `E_multi_document` | 15 | 0 |
| `F_similar_distractor` | 10 | 0 |
| `G_no_answer` | 10 | 0 |
| `H_investment_boundary` | 10 | 0 |

## Guardrails

- Do not promote draft labels without manual confirmation.
- Do not create official train/held-out splits from preview artifacts.
- Do not run automatic tuning until official split and baseline gates pass.
