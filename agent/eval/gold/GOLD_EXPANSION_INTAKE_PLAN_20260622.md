# 3.3 Gold Expansion Intake Plan - 2026-06-22

## Purpose

This plan turns the current 3.3 coverage report into a manual intake checklist.
It does not add rows to `eval/gold/eval_gold_retrieval.jsonl`.

## Current State

Evidence:

- Coverage report: `eval/gold/GOLD_EXPANSION_COVERAGE_20260622.md`
- Coverage JSON: `eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json`
- Candidate queue: `eval/gold/gray_candidates_20260622.jsonl`
- Candidate worksheet: `eval/gold/GRAY_CANDIDATE_LABELING_WORKSHEET_20260622.md`
- Reviewed labels: `eval/gold/reviewed_labels_20260622.jsonl`
- Reviewed-label draft: `eval/gold/reviewed_labels_draft_20260622.jsonl`
- Draft impact: `eval/gold/REVIEWED_LABELS_DRAFT_IMPACT_20260622.md`
- Draft confirmation packet: `eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md`
- Official-shape reviewed-label preview: `eval/gold/reviewed_labels_official_preview_20260622.jsonl`
- Official-shape preview coverage: `eval/gold/REVIEWED_LABEL_OFFICIAL_PREVIEW_COVERAGE_20260622.md`
- Promotion transaction dry-run:
  `eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.md`
- Reviewed-label pipeline state:
  `eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md`
- Guarded promotion apply attempt:
  `eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.md`
- Promotion sandbox simulation:
  `eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.md`
- Apply preflight:
  `eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md`
- Manual confirmation command packet:
  `eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md`
- Guarded rollback attempt:
  `eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.md`
- Draft text readability audit: `eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.md`
- Candidate text readability audit: `eval/gold/GOLD_CANDIDATE_TEXT_READABILITY_AUDIT_20260622.md`
- Official reviewed-label coverage: `eval/gold/REVIEWED_LABEL_COVERAGE_20260622.md`
- Draft reviewed-label coverage: `eval/gold/REVIEWED_LABEL_DRAFT_COVERAGE_20260622.md`
- Reviewed-label promotion audit: `eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md`
- Expanded gold preview summary: `eval/gold/EXPANDED_GOLD_PREVIEW_20260622.md`
- Draft expanded gold coverage: `eval/gold/DRAFT_EXPANDED_GOLD_COVERAGE_20260622.md`
- Draft split preview: `eval/gold/splits/preview/RETRIEVAL_SPLIT_PREVIEW_20260622.md`

Counts:

- Formal gold cases: 50
- Current candidate cases: 80
- Reviewed labels: 0
- Projected total if all current candidates are accepted: 130
- Minimum additional accepted cases to reach 100 total: 0
- Draft suggested accepts: 65
- Draft suggested merges with existing gold: 15
- Draft confirmation packet: 80 rows, 0 missing candidate references
- Official-shape preview: 80 rows, validator ok, projected formal count 115
- Official-shape preview class deficits: 0
- Promotion transaction dry-run: manual transaction ready, dry-run only
- Official reviewed-label file: 0 rows, 1 byte; no official promotion has been written
- Reviewed-label pipeline state: pending manual confirmation; not ready for gold expansion
- Guarded promotion applier without confirmation: applied=false; official file unchanged
- Promotion sandbox simulation: sandbox stage ready for gold expansion; real official unchanged
- Apply preflight: apply ready; waiting for explicit confirmation token
- Manual confirmation command packet: packet ready; includes guarded apply command and post-apply verification commands
- Guarded rollback: tool ready; current rollback attempt blocked because no real apply backup exists
- Text readability audits: draft and candidate prompt text both `ok=true`
- Projected formal total if all draft accepts are confirmed: 115
- Official reviewed-label coverage: blocked because reviewed labels are still empty
- Reviewed-label promotion audit: blocked because reviewed labels are still empty
- Draft reviewed-label coverage: no projected class deficits if all 65 accepts are confirmed
- Official expanded gold preview: 50 rows because no official reviewed labels are accepted yet
- Draft expanded gold preview: 115 rows with all class targets covered
- Draft split preview: train 80, held-out 35, overlap 0
- Current zero-candidate gap: none
- Completed first intake batch: 4 `H_investment_boundary` candidates added
- Completed first intake batch: 13 `A_exact_news_qa` candidates added
- Completed first intake batch: 10 `B_context_follow_up` candidates added
- Completed first intake batch: 7 `C_time_sensitive` candidates added
- Completed first intake batch: 7 `D_source_limited` candidates added
- Completed first intake batch: 5 `E_multi_document` candidates added
- Completed first intake batch: 3 `F_similar_distractor` candidates added
- Completed first intake batch: 3 `G_no_answer` candidates added
- Completed merge replacement batch: 15 candidates added

## Two Intake Targets

### Target A: Automatic Tuning Entry Lower Bound

This is the minimum before automatic weight search can even be considered:

- total formal gold cases >= 100
- held-out split >= 30
- each major class >= 10
- train and held-out 3.2E baselines generated
- `scripts/check_gold_tuning_gate.py` returns `ok=true`

If all 65 draft suggested accepts are confirmed, the 100-case lower bound and
the documented full class target are covered. Manual review, fixed split
creation, and train/held-out 3.2E
baselines are still required before automatic tuning can open.

### Target B: Full Class Coverage Target

The class coverage targets in `eval/gold/README_3_3_GOLD_EXPANSION.md` are
stricter than the entry lower bound. They sum to 115 cases, not 100.

If all 80 raw candidates are accepted as new rows, the queue has additional
slack above the documented full class coverage target. The draft review still
flags 15 likely merges with existing formal gold, but replacement candidates now
cover the same class deficits if those merge rows stay merged.

## Intake Allocation

| Case type | Formal now | Current candidates | Projected if accepted | Gate minimum deficit to 10 | Full target | Full target deficit | Intake priority |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `A_exact_news_qa` | 6 | 15 | 21 | 0 | 20 | 0 | Filled with replacement slack |
| `B_context_follow_up` | 6 | 20 | 26 | 0 | 20 | 0 | Filled with replacement slack |
| `C_time_sensitive` | 6 | 11 | 17 | 0 | 15 | 0 | Filled with replacement slack |
| `D_source_limited` | 7 | 9 | 16 | 0 | 15 | 0 | Filled with replacement slack |
| `E_multi_document` | 7 | 11 | 18 | 0 | 15 | 0 | Filled with replacement slack |
| `F_similar_distractor` | 6 | 5 | 11 | 0 | 10 | 0 | Filled with replacement slack |
| `G_no_answer` | 6 | 5 | 11 | 0 | 10 | 0 | Filled with replacement slack |
| `H_investment_boundary` | 6 | 4 | 10 | 0 | 10 | 0 | Filled for current batch |

## Recommended Next Intake Batch

No further candidate intake is needed for the documented full class coverage
target if the current queue is accepted. Prioritize manual review and reviewed
label output before any formal gold promotion.

Suggested batch:

| Case type | New candidate target | Notes |
| --- | ---: | --- |
| `A_exact_news_qa` | 0 | First 13-candidate intake batch has been added; review it before adding more. |
| `B_context_follow_up` | 0 | First 10-candidate intake batch has been added; review it before adding more. |
| `C_time_sensitive` | 0 | First 7-candidate intake batch has been added; review it before adding more. |
| `D_source_limited` | 0 | First 7-candidate intake batch has been added; review it before adding more. |
| `E_multi_document` | 0 | First 5-candidate intake batch has been added; review it before adding more. |
| `F_similar_distractor` | 0 | First 3-candidate intake batch has been added; review it before adding more. |
| `G_no_answer` | 0 | First 3-candidate intake batch has been added; review it before adding more. |
| `H_investment_boundary` | 0 | First 4-candidate intake batch has been added; review it before adding more. |

## Manual Intake Rules

For each new candidate:

- add it first to a candidate queue, not to formal gold,
- use a stable `candidate_*` id,
- include one of the documented `case_type` values,
- include natural user wording in `query_or_turns`,
- record why the case is useful in `reason`,
- keep `status` as `needs_label_review`,
- run `scripts/validate_gold_candidates.py`,
- only write reviewed decisions to `eval/gold/reviewed_labels_20260622.jsonl`,
- use `eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md` as the manual
  review checklist for the current draft,
- inspect `eval/gold/reviewed_labels_official_preview_20260622.jsonl` as the
  exact official-file shape before copying anything into official labels,
- use `eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.md` as
  the final transaction checklist before any manual copy into official labels,
- use `eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md` to verify whether
  the official reviewed-label file is still waiting for manual confirmation or
  is ready to drive gold expansion,
- use `scripts/apply_reviewed_labels_promotion.py` for the manual promotion
  step after explicit confirmation; it requires the exact token
  `COPY_REVIEWED_LABELS_20260622`, validates the preview, and creates a backup
  before writing official labels,
- use `eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.md` as evidence that
  the same preview reaches `reviewed_labels_ready_for_gold_expansion` in a
  sandbox while leaving the real official file unchanged,
- use `eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md` as the final
  readiness check before requesting `COPY_REVIEWED_LABELS_20260622`,
- use `eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md` to review the
  exact guarded apply command and required post-apply checks,
- use `scripts/rollback_reviewed_labels_promotion.py` only after a successful
  apply creates a backup and only with the explicit rollback token,
- use the text readability audit reports if terminal output displays Chinese
  incorrectly,
- run `scripts/validate_gold_reviewed_labels.py` before formal gold insertion.
- run `scripts/report_reviewed_label_coverage.py` before formal gold insertion.
- run `scripts/audit_gold_promotion_readiness.py` before formal gold insertion.
- run `scripts/build_expanded_gold_preview.py` before formal gold insertion.
- use `scripts/build_retrieval_split_preview.py` only for preview balance checks,
  not as an official split.

## Guardrails

- Do not install `sentence-transformers`.
- Do not create `scripts/tune_rag_weights.py`.
- Do not use these candidates as held-out cases before fixed split creation.
- Do not tune weights from the candidate queue.
- Do not tune weights from `eval/gold/splits/preview/`.
- Do not modify `eval/gold/eval_gold_retrieval.jsonl` until reviewed labels pass.

## Next Action

Review `eval/gold/reviewed_labels_draft_20260622.jsonl`, confirm which draft
accepts should become formal gold, and keep merge rows as non-new coverage
unless a reviewer rewrites them. Replacement rows are already present for the
merge-related class deficits.

Use `eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md` as the row-level
confirmation checklist while reviewing the draft.

After writing confirmed decisions to `eval/gold/reviewed_labels_20260622.jsonl`,
rerun `scripts/report_reviewed_label_coverage.py` and require no reviewed-label
coverage blockers before formal promotion.

The current promotion transaction dry-run has no blockers, but it is still
dry-run only. It means a reviewer can perform the manual confirmation step; it
does not mean official labels have already been promoted.

Then run `scripts/audit_gold_promotion_readiness.py`, require
`formal_promotion_ready=true`, and run `scripts/build_expanded_gold_preview.py`
before replacing or editing the formal gold file.
