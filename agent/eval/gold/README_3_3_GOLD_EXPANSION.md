# 3.3 Gold Expansion Rules

## Goal

Expand retrieval gold from 50 cases to 100-150 cases before automatic weight tuning.

## Sources

- Real gray queries with user-visible uncertainty or failure.
- Existing 3.2E failed cases.
- Source-constrained queries.
- Time-sensitive queries.
- Multi-document synthesis queries.
- No-answer and investment-boundary queries.

## Current Candidate Queue

- Raw candidate queue: `eval/gold/gray_candidates_20260622.jsonl`
- Candidate queue validator: `scripts/validate_gold_candidates.py`
- Manual labeling worksheet:
  `eval/gold/GRAY_CANDIDATE_LABELING_WORKSHEET_20260622.md`
- Reviewed label output: `eval/gold/reviewed_labels_20260622.jsonl`
- Reviewed label validator: `scripts/validate_gold_reviewed_labels.py`
- Reviewed-label draft output: `eval/gold/reviewed_labels_draft_20260622.jsonl`
- Reviewed-label draft summary: `eval/gold/REVIEWED_LABELS_DRAFT_20260622.md`
- Reviewed-label draft impact:
  `eval/gold/REVIEWED_LABELS_DRAFT_IMPACT_20260622.md`
- Reviewed-label confirmation packet:
  `eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md`
- Reviewed-label official-shape preview:
  `eval/gold/reviewed_labels_official_preview_20260622.jsonl`
- Reviewed-label official preview coverage:
  `eval/gold/REVIEWED_LABEL_OFFICIAL_PREVIEW_COVERAGE_20260622.md`
- Reviewed-label conditional approval checker:
  `scripts/check_reviewed_label_conditions.py`
- Reviewed-label conditional approval report:
  `eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md`
- Draft label text readability audit:
  `eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.md`
- Candidate text readability audit:
  `eval/gold/GOLD_CANDIDATE_TEXT_READABILITY_AUDIT_20260622.md`
- Official reviewed-label coverage:
  `eval/gold/REVIEWED_LABEL_COVERAGE_20260622.md`
- Draft reviewed-label coverage:
  `eval/gold/REVIEWED_LABEL_DRAFT_COVERAGE_20260622.md`
- Reviewed-label coverage reporter:
  `scripts/report_reviewed_label_coverage.py`
- Reviewed-label promotion auditor:
  `scripts/audit_gold_promotion_readiness.py`
- Reviewed-label promotion audit:
  `eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md`
- Reviewed-label promotion transaction dry-run:
  `scripts/plan_reviewed_labels_promotion.py`
- Reviewed-label promotion transaction report:
  `eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.md`
- Reviewed-label pipeline state checker:
  `scripts/check_reviewed_label_pipeline_state.py`
- Reviewed-label pipeline state report:
  `eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md`
- Guarded reviewed-label promotion applier:
  `scripts/apply_reviewed_labels_promotion.py`
- Guarded promotion apply attempt report:
  `eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.md`
- Reviewed-label promotion sandbox simulator:
  `scripts/simulate_reviewed_labels_promotion.py`
- Reviewed-label promotion sandbox report:
  `eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.md`
- Reviewed-label apply preflight checker:
  `scripts/check_reviewed_label_apply_preflight.py`
- Reviewed-label apply preflight report:
  `eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md`
- Manual confirmation command packet renderer:
  `scripts/render_reviewed_label_apply_command_packet.py`
- Manual confirmation command packet:
  `eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md`
- Guarded reviewed-label rollback tool:
  `scripts/rollback_reviewed_labels_promotion.py`
- Guarded rollback attempt report:
  `eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.md`
- Expanded gold preview builder:
  `scripts/build_expanded_gold_preview.py`
- Expanded gold preview summary:
  `eval/gold/EXPANDED_GOLD_PREVIEW_20260622.md`
- Retrieval split preview builder:
  `scripts/build_retrieval_split_preview.py`
- Retrieval split preview report:
  `eval/gold/splits/preview/RETRIEVAL_SPLIT_PREVIEW_20260622.md`
- Draft expanded gold coverage:
  `eval/gold/DRAFT_EXPANDED_GOLD_COVERAGE_20260622.md`
- Coverage report: `eval/gold/GOLD_EXPANSION_COVERAGE_20260622.md`
- Coverage reporter: `scripts/report_gold_expansion_coverage.py`
- Intake plan: `eval/gold/GOLD_EXPANSION_INTAKE_PLAN_20260622.md`
- Automatic tuning gate checker: `scripts/check_gold_tuning_gate.py`

The worksheet is not a gold set. It is a review aid for deciding which
candidates should become formal gold rows.

Validate the candidate queue before manual review:

```powershell
python scripts/validate_gold_candidates.py --candidates eval/gold/gray_candidates_20260622.jsonl
```

Validate reviewed labels before promoting any row into the formal gold set:

```powershell
python scripts/validate_gold_reviewed_labels.py --candidates eval/gold/gray_candidates_20260622.jsonl --labels eval/gold/reviewed_labels_20260622.jsonl
```

Check the stricter conditional-approval rules before apply:

```powershell
python scripts/check_reviewed_label_conditions.py --labels eval/gold/reviewed_labels_official_preview_20260622.jsonl --evidence-corpus work/econ_rag_experiment/clean_merged_recent_econ.jsonl --report eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md --json-report eval/gold/REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.json
```

Render a manual confirmation packet from draft reviewed labels:

```powershell
python scripts/render_reviewed_label_confirmation_packet.py --candidates eval/gold/gray_candidates_20260622.jsonl --labels eval/gold/reviewed_labels_draft_20260622.jsonl --report eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md --json-report eval/gold/REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.json
```

Build an official-shape preview without editing the official reviewed-label file:

```powershell
python scripts/build_reviewed_labels_official_preview.py --draft-labels eval/gold/reviewed_labels_draft_20260622.jsonl --output eval/gold/reviewed_labels_official_preview_20260622.jsonl --summary eval/gold/reviewed_labels_official_preview_20260622.json --report eval/gold/REVIEWED_LABELS_OFFICIAL_PREVIEW_20260622.md
```

Audit prompt text readability before manual review:

```powershell
python scripts/audit_gold_text_readability.py --source eval/gold/reviewed_labels_draft_20260622.jsonl --fallback-source eval/gold/gray_candidates_20260622.jsonl --report eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.md --json-report eval/gold/GOLD_TEXT_READABILITY_AUDIT_20260622.json
python scripts/audit_gold_text_readability.py --source eval/gold/gray_candidates_20260622.jsonl --report eval/gold/GOLD_CANDIDATE_TEXT_READABILITY_AUDIT_20260622.md --json-report eval/gold/GOLD_CANDIDATE_TEXT_READABILITY_AUDIT_20260622.json
```

Project reviewed-label coverage before promotion:

```powershell
python scripts/report_reviewed_label_coverage.py --gold eval/gold/eval_gold_retrieval.jsonl --labels eval/gold/reviewed_labels_20260622.jsonl --report eval/gold/REVIEWED_LABEL_COVERAGE_20260622.md --json-report eval/gold/REVIEWED_LABEL_COVERAGE_20260622.json
```

Audit formal promotion readiness before editing formal gold:

```powershell
python scripts/audit_gold_promotion_readiness.py --gold eval/gold/eval_gold_retrieval.jsonl --candidates eval/gold/gray_candidates_20260622.jsonl --official-labels eval/gold/reviewed_labels_20260622.jsonl --draft-labels eval/gold/reviewed_labels_draft_20260622.jsonl --report eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md --json-report eval/gold/REVIEWED_LABEL_PROMOTION_AUDIT_20260622.json
```

Plan the manual reviewed-label promotion transaction without editing official labels:

```powershell
python scripts/plan_reviewed_labels_promotion.py --preview eval/gold/reviewed_labels_official_preview_20260622.jsonl --official eval/gold/reviewed_labels_20260622.jsonl --report eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.md --json-report eval/gold/REVIEWED_LABEL_PROMOTION_TRANSACTION_DRY_RUN_20260622.json
```

Check the official reviewed-label pipeline state after, or before, manual confirmation:

```powershell
python scripts/check_reviewed_label_pipeline_state.py --gold eval/gold/eval_gold_retrieval.jsonl --candidates eval/gold/gray_candidates_20260622.jsonl --official-labels eval/gold/reviewed_labels_20260622.jsonl --preview-labels eval/gold/reviewed_labels_official_preview_20260622.jsonl --report eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.md --json-report eval/gold/REVIEWED_LABEL_PIPELINE_STATE_20260622.json
```

Apply the reviewed-label promotion only after explicit human confirmation:

```powershell
python scripts/apply_reviewed_labels_promotion.py --preview eval/gold/reviewed_labels_official_preview_20260622.jsonl --official eval/gold/reviewed_labels_20260622.jsonl --backup-dir eval/gold/backups --candidates eval/gold/gray_candidates_20260622.jsonl --confirm COPY_REVIEWED_LABELS_20260622 --report eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.md --json-report eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.json
```

Without the exact confirmation token, the guarded applier refuses to write the
official file and records `applied=false`.

Simulate the same promotion in a sandbox without editing the real official file:

```powershell
python scripts/simulate_reviewed_labels_promotion.py --gold eval/gold/eval_gold_retrieval.jsonl --candidates eval/gold/gray_candidates_20260622.jsonl --preview eval/gold/reviewed_labels_official_preview_20260622.jsonl --official eval/gold/reviewed_labels_20260622.jsonl --sandbox-dir eval/gold/sandbox/promotion_20260622 --report eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.md --json-report eval/gold/REVIEWED_LABEL_PROMOTION_SANDBOX_20260622.json
```

Run the final apply preflight before requesting the confirmation token:

```powershell
python scripts/check_reviewed_label_apply_preflight.py --gold eval/gold/eval_gold_retrieval.jsonl --candidates eval/gold/gray_candidates_20260622.jsonl --preview eval/gold/reviewed_labels_official_preview_20260622.jsonl --official eval/gold/reviewed_labels_20260622.jsonl --sandbox-dir eval/gold/sandbox/apply_preflight_20260622 --report eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md --json-report eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.json
```

Render the manual confirmation command packet from the preflight result:

```powershell
python scripts/render_reviewed_label_apply_command_packet.py --preflight eval/gold/REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.json --report eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md --json-report eval/gold/REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.json
```

Rollback is also guarded and only applies after a successful apply creates a backup:

```powershell
python scripts/rollback_reviewed_labels_promotion.py --apply-report eval/gold/REVIEWED_LABEL_PROMOTION_APPLY_20260622.json --official eval/gold/reviewed_labels_20260622.jsonl --rollback-backup-dir eval/gold/backups --confirm ROLLBACK_REVIEWED_LABELS_20260622 --report eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.md --json-report eval/gold/REVIEWED_LABEL_PROMOTION_ROLLBACK_20260622.json
```

Build an expanded gold preview without modifying formal gold:

```powershell
python scripts/build_expanded_gold_preview.py --gold eval/gold/eval_gold_retrieval.jsonl --labels eval/gold/reviewed_labels_20260622.jsonl --output eval/gold/eval_gold_retrieval_expanded_preview_20260622.jsonl --summary eval/gold/eval_gold_retrieval_expanded_preview_20260622.json
```

Build a draft split preview only after a preview gold file exists:

```powershell
python scripts/build_retrieval_split_preview.py --gold eval/gold/eval_gold_retrieval_draft_expanded_preview_20260622.jsonl --train-output eval/gold/splits/preview/retrieval_train_preview_20260622.jsonl --heldout-output eval/gold/splits/preview/retrieval_heldout_preview_20260622.jsonl --summary eval/gold/splits/preview/retrieval_split_preview_20260622.json --report eval/gold/splits/preview/RETRIEVAL_SPLIT_PREVIEW_20260622.md
```

This split is a preview only. It does not satisfy the official tuning gate.

Regenerate coverage after candidate review:

```powershell
python scripts/report_gold_expansion_coverage.py --gold eval/gold/eval_gold_retrieval.jsonl --candidates eval/gold/gray_candidates_20260622.jsonl --report eval/gold/GOLD_EXPANSION_COVERAGE_20260622.md --json-report eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json
```

Current coverage summary:

- formal gold cases: 50
- current candidates: 80
- projected total if all candidates are accepted: 130
- additional reviewed/accepted cases still needed for 100 total: 0
- reviewed-label draft rows: 80
- draft suggested accepts: 65
- draft suggested merges with existing gold: 15
- confirmation packet rows: 80, missing candidate references: 0
- official-shape preview rows: 80, validator `ok=true`
- conditional approval: `ok=true`; E evidence ids are complete, C evidence dates match prompt windows, and G/H answer-boundary fields are explicit
- official-shape preview projected formal total: 115, class deficits: 0
- promotion transaction dry-run: `manual_transaction_ready=true`, dry-run only
- official reviewed-label file remains empty: rows=0, bytes=1
- reviewed-label pipeline state: `pending_manual_confirmation`, ready for gold expansion=`false`
- guarded promotion applier without confirmation: `applied=false`, official rows remain 0
- sandbox promotion simulation: applied in sandbox, ready for gold expansion=`true`, real official unchanged=`true`
- apply preflight: `apply_ready=true`, including `conditional_approval_ok=true`, awaiting explicit confirmation token
- manual confirmation command packet: `packet_ready=true`, contains guarded apply command and post-apply verification commands
- guarded rollback tool: current attempt `rolled_back=false` because no real apply backup exists
- text readability audit: draft and candidate prompts both `ok=true`
- projected formal total if all draft accepts are confirmed: 115
- official reviewed-label coverage currently blocked because the official file is empty
- official promotion audit currently blocked because the official reviewed-label file is empty
- draft reviewed-label coverage has no class deficits if all draft accepts are confirmed
- official expanded preview currently remains 50 rows
- draft expanded preview reaches 115 rows and all documented class targets
- draft split preview reaches train=80 and held-out=35, with `evidence_group_count=48` and `evidence_group_overlap_count=0`
- `candidate_time_recent_014` was corrected from "2026年5月下旬" to "2026年5月中旬" because evidence `news:jjrb:543874085db2b6c0` was published on 2026-05-20
- current zero-candidate class gap: none
- `H_investment_boundary` first intake batch has been added as candidates
- `A_exact_news_qa` first intake batch has been added as candidates
- `B_context_follow_up` first intake batch has been added as candidates
- `C_time_sensitive` first intake batch has been added as candidates
- `D_source_limited` first intake batch has been added as candidates
- `E_multi_document` first intake batch has been added as candidates
- `F_similar_distractor` first intake batch has been added as candidates
- `G_no_answer` first intake batch has been added as candidates
- merge replacement intake batch has been added as candidates

The manual intake plan separates raw candidate coverage from reviewed coverage.
The raw queue now includes replacement candidates for the 15 likely merges. If
the draft accepts are confirmed and the merge rows stay merged, projected formal
coverage still reaches the full class target; see
`REVIEWED_LABELS_DRAFT_IMPACT_20260622.md` before promotion.

## Label Requirements

Each gold case must include:

- stable `id`
- `question` or ordered `turns`
- `expected_route`
- `gold_evidence_ids`
- `should_answer`
- `should_refuse`
- `must_have_citations`
- `case_type`
- `notes`

## Split Policy

When the gold set reaches at least 100 cases:

- train: 70%
- held-out: 30%

Train is used for weight search. Held-out is used only for final verification.
Do not move failed held-out cases into train during the same tuning cycle.
Split by evidence group, not by individual row: all rows sharing the same
`gold_evidence_ids` or parent news id must stay in the same split to avoid
leaking the same article into both train and held-out.

Preview split files under `eval/gold/splits/preview/` are dry-run artifacts.
They are useful for checking class balance, but they are not official split
files and must not be used for decision-making automatic tuning.

## Minimum Class Coverage

- A_exact_news_qa: at least 20
- B_context_follow_up: at least 20
- C_time_sensitive: at least 15
- D_source_limited: at least 15
- E_multi_document: at least 15
- F_similar_distractor: at least 10
- G_no_answer: at least 10
- H_investment_boundary: at least 10

## Automatic Tuning Entry Gate

Do not run decision-making automatic tuning until:

- total gold cases >= 100,
- held-out cases >= 30,
- each major class has at least 10 cases,
- current 3.2E baseline is re-run on both train and held-out.

Check the gate before creating or running any weight-tuning script:

```powershell
python scripts/check_gold_tuning_gate.py --coverage eval/gold/GOLD_EXPANSION_COVERAGE_20260622.json
```

Current status: gate closed. The formal gold set has 50 cases, no official
fixed train/held-out split exists yet, and train/held-out 3.2E baseline reports
have not been generated. The draft split preview does not open this gate.

## Future Tuning Boundary

When automatic tuning becomes eligible, keep the search space near the current
3.2E weights:

```json
{
  "body_bonus": [0.4, 1.2],
  "entity_text_bonus": [0.25, 0.75],
  "analysis_section_bonus": [0.6, 1.8],
  "diversity_max_per_source": [2, 3],
  "diversity_score_tolerance": [1.0, 3.0]
}
```

## Future Objective Function

Use this score on train only:

```text
score =
  0.40 * Recall@5
+ 0.45 * EvidenceRecall@5
+ 0.05 * RouteAccuracy
- 0.10 * LatencyPenalty
```

Where:

```text
LatencyPenalty = max(0, (LatencyP95 - 1200) / 1200)
```

## Held-out Promotion Rule

A tuned weight set can replace 3.2E r2 only if held-out satisfies:

```text
heldout Recall@5 >= 3.2E r2 heldout Recall@5
heldout EvidenceRecall@5 >= 3.2E r2 heldout EvidenceRecall@5
heldout RouteAccuracy >= 0.96
heldout LatencyP95 <= 1500 ms
no critical case class regresses by more than one case
```
