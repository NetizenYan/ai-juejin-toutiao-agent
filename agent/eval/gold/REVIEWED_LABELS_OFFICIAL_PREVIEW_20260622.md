# Reviewed Labels Official Preview

## Preview Only

This file has the same row shape expected by the official reviewed-label file, but it is not official.

## Summary

- Preview output: `eval\gold\reviewed_labels_official_preview_20260622.jsonl`
- Rows: 80
- Accept as gold: 65
- Merge with existing: 15
- Needs evidence lookup: 0
- Reject: 0

## Guardrails

- Do not treat this preview as manual confirmation.
- Do not overwrite `eval/gold/reviewed_labels_20260622.jsonl` without reviewer approval.
- Validate this preview before any manual promotion step.
- Keep automatic tuning closed until the official split and baselines exist.
