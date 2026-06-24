# Reviewed Label Conditional Approval

This report checks the manual-review conditions that must be true before apply.

## Decision

- Conditions ok: `true`
- Split policy: `group_by_evidence_or_parent_news_id`

## Checked Counts

| Case type | Accepted rows checked |
| --- | ---: |
| `B_context_follow_up` | 14 |
| `C_time_sensitive` | 9 |
| `E_multi_document` | 8 |
| `G_no_answer` | 4 |
| `H_investment_boundary` | 4 |

## Errors

- None.

## Warnings

- None.

## Guardrails

- E multi-document rows must use complete evidence ids.
- C time-sensitive rows must match the evidence publish date window.
- G/H rows must encode refusal boundary and allowed factual summary explicitly.
- Future train/held-out splits must group by evidence id or parent news id.
