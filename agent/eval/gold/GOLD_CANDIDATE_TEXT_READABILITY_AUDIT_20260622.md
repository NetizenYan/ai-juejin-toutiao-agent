# Gold Text Readability Audit

This report checks prompt text readability for manual review files. It is read-only.

## Summary

- Source: `eval\gold\gray_candidates_20260622.jsonl`
- OK: `true`
- Rows: 80
- Fallback rows: 0
- Rows with prompt text: 80
- Rows with CJK text: 80
- Rows missing prompt text: 0
- Rows without CJK text: 0
- Rows with Unicode replacement characters: 0
- Rows with ASCII question marks: 0
- Rows with mojibake marker patterns: 0

## Problem Rows

- None.

## Notes

- If PowerShell displays Chinese as mojibake, inspect the Markdown or JSONL file in a UTF-8 aware editor.
- This audit checks stored file content, not terminal rendering.
- Do not use this report to promote labels without manual review.
