# Reviewed Label Promotion Transaction Dry-Run

Dry-run only. This report does not modify the official reviewed-label file.

## Decision

- Manual transaction ready: `true`
- Dry-run only: `true`

## Preview File

- Path: `eval\gold\reviewed_labels_official_preview_20260622.jsonl`
- Exists: `true`
- Rows: 80
- Bytes: 38911
- SHA-256: `4016bb5bdde7c2f8022b22e6bae0f8855665c1465f95fa5d76a5df185992e632`

## Official File

- Path: `eval\gold\reviewed_labels_20260622.jsonl`
- Exists: `true`
- Rows: 0
- Bytes: 1
- SHA-256: `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`

## Preview Decision Counts

| Decision | Rows |
| --- | ---: |
| `accept_as_gold` | 65 |
| `merge_with_existing` | 15 |
| `needs_evidence_lookup` | 0 |
| `reject` | 0 |

## Blockers

- None for the manual reviewed-label promotion transaction.

## Warnings

- None.

## Required Manual Actions

1. manual confirmation required before copying the preview into the official reviewed-label file
2. validate the preview against the gray candidate source
3. back up the current official reviewed-label file and record its hash
4. after human approval only, copy the preview file content into the official reviewed-label file
5. rerun reviewed-label validation, coverage, promotion audit, split preview, and the tuning gate check
6. keep automatic tuning closed until official train/held-out splits and baseline reports exist

## Guardrails

- This tool has no apply mode.
- Do not create official split files from preview-only artifacts.
- Do not run automatic tuning until the official gate is open.
