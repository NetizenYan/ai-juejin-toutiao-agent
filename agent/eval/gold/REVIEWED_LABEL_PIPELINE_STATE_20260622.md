# Reviewed Label Pipeline State

This report is read-only. It does not modify official labels, formal gold, split files, or tuning config.

## Decision

- Reviewed-label stage: `reviewed_labels_ready_for_gold_expansion`
- Ready for gold expansion: `true`
- Automatic tuning gate: `closed`

## Official Reviewed Labels

- Path: `eval\gold\reviewed_labels_20260622.jsonl`
- Rows: 80
- Bytes: 41177
- SHA-256: `17ac5562dcdb68457e778a3682d4c41c3689ce54697633d5cc8abb9087218376`
- Validation OK: `true`

## Coverage Projection From Official Labels

- Formal gold count now: 50
- Official reviewed-label rows: 80
- Accepted rows: 65
- Merge rows: 15
- Projected formal count after accepts: 115

## Blockers

- None for reviewed-label gold-expansion readiness.

## Automatic Tuning Gate Blockers

- formal gold count 50 is below 100
- A_exact_news_qa has 6 formal cases, below 10
- B_context_follow_up has 6 formal cases, below 10
- C_time_sensitive has 6 formal cases, below 10
- D_source_limited has 7 formal cases, below 10
- E_multi_document has 7 formal cases, below 10
- F_similar_distractor has 6 formal cases, below 10
- G_no_answer has 6 formal cases, below 10
- H_investment_boundary has 6 formal cases, below 10
- train split is missing
- held-out split is missing
- train baseline report is missing
- held-out baseline report is missing

## Warnings

- None.

## Next Actions

- build the expanded gold preview from official reviewed labels
- create official train and held-out splits only after formal gold is updated
- keep automatic tuning disabled until the tuning gate returns ok=true

## Guardrails

- Do not run automatic tuning while the gate is closed.
- Do not treat preview artifacts as official split files.
- Do not install `sentence-transformers` for this 3.3 gate work.
