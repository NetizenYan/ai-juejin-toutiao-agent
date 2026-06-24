# Expanded Gold Preview - 2026-06-22

## Purpose

This document tracks dry-run expanded gold files created from reviewed-label
decisions. These files are previews only and do not replace
`eval/gold/eval_gold_retrieval.jsonl`.

## Preview Files

| File | Source labels | Rows | Meaning |
| --- | --- | ---: | --- |
| `eval_gold_retrieval_expanded_preview_20260622.jsonl` | `reviewed_labels_20260622.jsonl` | 50 | Official reviewed labels are still empty, so no rows are added. |
| `eval_gold_retrieval_draft_expanded_preview_20260622.jsonl` | `reviewed_labels_draft_20260622.jsonl` | 115 | Draft-only preview if all 65 draft accepts are confirmed and 15 merge rows stay merged. |

## Draft Preview Coverage

The draft expanded preview reaches the documented class targets:

| Case type | Preview rows | Target |
| --- | ---: | ---: |
| `A_exact_news_qa` | 20 | 20 |
| `B_context_follow_up` | 20 | 20 |
| `C_time_sensitive` | 15 | 15 |
| `D_source_limited` | 15 | 15 |
| `E_multi_document` | 15 | 15 |
| `F_similar_distractor` | 10 | 10 |
| `G_no_answer` | 10 | 10 |
| `H_investment_boundary` | 10 | 10 |

Coverage report:

- `eval/gold/DRAFT_EXPANDED_GOLD_COVERAGE_20260622.md`
- `eval/gold/DRAFT_EXPANDED_GOLD_COVERAGE_20260622.json`

## Draft Split Preview

The draft expanded preview has a deterministic split preview:

- train preview: `eval/gold/splits/preview/retrieval_train_preview_20260622.jsonl`
- held-out preview: `eval/gold/splits/preview/retrieval_heldout_preview_20260622.jsonl`
- summary JSON: `eval/gold/splits/preview/retrieval_split_preview_20260622.json`
- report: `eval/gold/splits/preview/RETRIEVAL_SPLIT_PREVIEW_20260622.md`

Preview counts:

- input: 115
- train: 80
- held-out: 35
- overlap: 0

This is only a balance check for the draft preview. It is not the official
3.3 tuning split.

## Guardrails

- Do not copy a preview file over `eval_gold_retrieval.jsonl`.
- Do not promote preview split files to official split files before manual confirmation.
- Do not run automatic tuning from preview files.
- Promote only from validated official reviewed labels.
