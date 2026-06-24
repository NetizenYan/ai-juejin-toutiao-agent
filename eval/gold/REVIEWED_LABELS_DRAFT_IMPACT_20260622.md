# Reviewed Labels Draft Impact - 2026-06-22

## Purpose

This document explains the impact of
`eval/gold/reviewed_labels_draft_20260622.jsonl`.

The draft is a review aid only. It is not the formal reviewed-label file and
does not modify `eval/gold/eval_gold_retrieval.jsonl`.

## Draft Summary

- Formal gold cases: 50
- Raw candidate rows: 80
- Draft rows: 80
- Suggested `accept_as_gold`: 65
- Suggested `merge_with_existing`: 15
- Suggested `needs_evidence_lookup`: 0
- Suggested `reject`: 0
- Projected formal total if all suggested accepts are confirmed: 115

## Why This Matters

The raw candidate coverage report shows projected total 130 if every candidate
is accepted as a new gold row.

The draft triage found 15 candidates that appear to map to existing formal gold
ids. If reviewers keep those as `merge_with_existing`, they should not be
counted as new coverage. A 15-row replacement batch has been added so the draft
accept rows can still cover the full class target while preserving those merges.

## Projected Coverage After Suggested Accepts

| Case type | Formal now | Suggested accepts | Projected formal | Full target | Remaining deficit |
| --- | ---: | ---: | ---: | ---: | ---: |
| `A_exact_news_qa` | 6 | 14 | 20 | 20 | 0 |
| `B_context_follow_up` | 6 | 14 | 20 | 20 | 0 |
| `C_time_sensitive` | 6 | 9 | 15 | 15 | 0 |
| `D_source_limited` | 7 | 8 | 15 | 15 | 0 |
| `E_multi_document` | 7 | 8 | 15 | 15 | 0 |
| `F_similar_distractor` | 6 | 4 | 10 | 10 | 0 |
| `G_no_answer` | 6 | 4 | 10 | 10 | 0 |
| `H_investment_boundary` | 6 | 4 | 10 | 10 | 0 |

## Suggested Merge Rows

| Candidate id | Existing gold id |
| --- | --- |
| `candidate_context_follow_001` | `context_follow_001` |
| `candidate_source_005` | `source_005` |
| `candidate_no_answer_006` | `no_answer_006` |
| `candidate_exact_econ_006` | `exact_econ_006` |
| `candidate_context_follow_002` | `context_follow_002` |
| `candidate_context_follow_003` | `context_follow_003` |
| `candidate_context_follow_004` | `context_follow_004` |
| `candidate_time_recent_003` | `time_recent_003` |
| `candidate_multi_doc_002` | `multi_doc_002` |
| `candidate_multi_doc_004` | `multi_doc_004` |
| `candidate_multi_doc_005` | `multi_doc_005` |
| `candidate_distractor_006` | `distractor_006` |
| `candidate_time_recent_007` | `time_recent_007` |
| `candidate_context_follow_005` | `context_follow_005` |
| `candidate_context_follow_006` | `context_follow_006` |

## Next Review Decision

For each `merge_with_existing` row, reviewers should choose one path:

- keep `merge_with_existing` and treat it as no new coverage,
- rewrite it into a genuinely new variation with stable evidence ids,
- reject it and use the replacement candidates now present in the queue.

The automatic tuning gate must remain closed until accepted rows are promoted
into formal gold, a fixed train/held-out split exists, and train/held-out 3.2E
baselines have been generated.
