# Manual Confirmation Command Packet

This packet is a command review aid. It does not execute any command.

## Decision

- Packet ready: `true`
- Requires human confirmation: `true`
- Confirmation token: `COPY_REVIEWED_LABELS_20260622`

## Apply Command

```powershell
python scripts\apply_reviewed_labels_promotion.py --preview eval\gold\reviewed_labels_official_preview_20260622.jsonl --official eval\gold\reviewed_labels_20260622.jsonl --backup-dir eval\gold\backups --candidates eval\gold\gray_candidates_20260622.jsonl --confirm COPY_REVIEWED_LABELS_20260622 --report eval\gold\REVIEWED_LABEL_PROMOTION_APPLY_20260622.md --json-report eval\gold\REVIEWED_LABEL_PROMOTION_APPLY_20260622.json
```

## Post-Apply Verification Commands

```powershell
python scripts\validate_gold_reviewed_labels.py --candidates eval\gold\gray_candidates_20260622.jsonl --labels eval\gold\reviewed_labels_20260622.jsonl
```

```powershell
python scripts\check_reviewed_label_conditions.py --labels eval\gold\reviewed_labels_20260622.jsonl --evidence-corpus work\econ_rag_experiment\clean_merged_recent_econ.jsonl --report eval\gold\REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md --json-report eval\gold\REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.json
```

```powershell
python scripts\check_reviewed_label_pipeline_state.py --gold eval\gold\eval_gold_retrieval.jsonl --candidates eval\gold\gray_candidates_20260622.jsonl --official-labels eval\gold\reviewed_labels_20260622.jsonl --preview-labels eval\gold\reviewed_labels_official_preview_20260622.jsonl --report eval\gold\REVIEWED_LABEL_PIPELINE_STATE_20260622.md --json-report eval\gold\REVIEWED_LABEL_PIPELINE_STATE_20260622.json
```

```powershell
python scripts\report_reviewed_label_coverage.py --gold eval\gold\eval_gold_retrieval.jsonl --labels eval\gold\reviewed_labels_20260622.jsonl --report eval\gold\REVIEWED_LABEL_COVERAGE_20260622.md --json-report eval\gold\REVIEWED_LABEL_COVERAGE_20260622.json
```

```powershell
python scripts\audit_gold_promotion_readiness.py --gold eval\gold\eval_gold_retrieval.jsonl --candidates eval\gold\gray_candidates_20260622.jsonl --official-labels eval\gold\reviewed_labels_20260622.jsonl --draft-labels eval\gold\reviewed_labels_draft_20260622.jsonl --report eval\gold\REVIEWED_LABEL_PROMOTION_AUDIT_20260622.md --json-report eval\gold\REVIEWED_LABEL_PROMOTION_AUDIT_20260622.json
```

```powershell
python scripts\build_expanded_gold_preview.py --gold eval\gold\eval_gold_retrieval.jsonl --labels eval\gold\reviewed_labels_20260622.jsonl --output eval\gold\eval_gold_retrieval_expanded_preview_20260622.jsonl --summary eval\gold\eval_gold_retrieval_expanded_preview_20260622.json
```

```powershell
python scripts\check_gold_tuning_gate.py --coverage eval\gold\GOLD_EXPANSION_COVERAGE_20260622.json
```

## Current Evidence

- Preview rows: 80
- Preview SHA-256: `17ac5562dcdb68457e778a3682d4c41c3689ce54697633d5cc8abb9087218376`
- Official rows before apply: 0
- Official SHA-256 before apply: `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`
- Sandbox stage: `reviewed_labels_ready_for_gold_expansion`
- Sandbox projected formal count: 115

## Blockers

- None in preflight. Explicit human confirmation is still required.

## Guardrails

- Do not run the apply command without explicit human approval.
- Do not run automatic tuning after apply; first update formal gold, splits, and baselines.
- Do not install sentence-transformers for this apply step.
