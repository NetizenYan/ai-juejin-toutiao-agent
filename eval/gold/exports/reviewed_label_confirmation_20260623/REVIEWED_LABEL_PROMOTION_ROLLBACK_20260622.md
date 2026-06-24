# Reviewed Label Promotion Rollback

This report records a guarded rollback attempt.

## Decision

- Rolled back: `false`
- Confirmation token: `mismatch`
- Current official backup created: `false`

## Official Labels

- Before rows: 0
- After rows: 0
- After SHA-256: `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`

## Blockers

- confirmation token mismatch
- apply report was not applied
- apply report has no created backup
- apply report backup path is missing

## Guardrails

- Use rollback only for a confirmed bad apply.
- Rerun reviewed-label validation and pipeline state after rollback.
