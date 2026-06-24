# Reviewed Label Manual Confirmation Export - 2026-06-23

## What You Are Confirming

You are reviewing whether to copy:

`eval/gold/reviewed_labels_official_preview_20260622.jsonl`

into the official reviewed-label file:

`eval/gold/reviewed_labels_20260622.jsonl`

No file in this export performs the copy by itself.

## Current Verified State

- Official reviewed-label file is still empty: 0 rows, 1 byte.
- Official-shape preview has 80 rows.
- Preview decisions: 65 `accept_as_gold`, 15 `merge_with_existing`.
- Preview validation passed.
- Conditional approval passed: E evidence ids are complete, C date windows match evidence publish dates, and G/H refusal boundaries allow factual summaries where appropriate.
- Apply preflight passed: `apply_ready=true`.
- Sandbox promotion passed: projected formal count 115, class deficits 0.
- Manual command packet is ready: `packet_ready=true`.
- Rollback tool exists, but current rollback is not applicable because no real apply backup exists yet.
- Automatic tuning gate remains closed.
- `sentence-transformers` is not installed.
- `scripts/tune_rag_weights.py` does not exist.
- Official train/held-out split files do not exist.
- `candidate_time_recent_014` is corrected to "2026年5月中旬" because its evidence was published on 2026-05-20.

## Files To Review First

1. `REVIEWED_LABEL_CONFIRMATION_PACKET_20260622.md`
   - Row-level candidate confirmation checklist.
2. `reviewed_labels_official_preview_20260622.jsonl`
   - Exact file content proposed for official reviewed labels.
3. `REVIEWED_LABEL_APPLY_PREFLIGHT_20260622.md`
   - Final readiness check before human confirmation.
4. `REVIEWED_LABEL_CONDITIONAL_APPROVAL_20260622.md`
   - E/C/G/H conditional-approval checks and date confirmations.
5. `REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md`
   - Exact guarded apply command and post-apply verification commands.

## Confirmation Token

The guarded apply command requires this exact token:

`COPY_REVIEWED_LABELS_20260622`

Only use it after you approve the preview content.

## Not Yet Allowed

- Do not run automatic tuning.
- Do not create official train/held-out splits.
- Do not install `sentence-transformers`.
- Do not treat sandbox files as official labels.

## After Approval

Run the guarded apply command from:

`REVIEWED_LABEL_APPLY_COMMAND_PACKET_20260622.md`

Then run every post-apply verification command listed in that same file.
