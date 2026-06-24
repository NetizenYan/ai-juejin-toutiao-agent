# ADR-20260621: Context Manager + Memory v1

## Status

Accepted for 3.1 gray validation.

## Context

The news agent now has economic RAG, Answer Contract + Validator v1, citation detail resolver, frontend citation detail, DeepSeek provider regression, and Data Source Risk Gate. The next product gap is multi-turn continuity: users naturally ask follow-up questions, carry answer constraints across turns, and refer to prior topics with pronouns.

The key risk is that conversation memory could be mistaken for news evidence. That would weaken the Answer Contract and increase hallucination risk.

## Decision

Implement a conservative Context Manager v1:

```text
Keep recent 4-6 turns as original messages.
Compress older context into structured session summary.
Extract active presentation constraints from user turns.
Record recent evidence ids only for reference resolution.
Mark all memory as use_as_evidence=false.
Keep RAG evidence_pack as the only factual source for news answers.
```

The implementation adds:

```text
harness/context_manager.py
CONTEXT_MANAGER_ENABLED
SESSION_SUMMARY_ENABLED
LONG_TERM_MEMORY_ENABLED
```

Session summaries are stored in `ai_message.evidence.context` rather than a new table.

## Prompt Boundary

The model receives separated context:

```xml
<session_context use_as_evidence="false">
Conversation summary and constraints. Not factual news evidence.
</session_context>

<recent_messages>
Recent raw turns.
</recent_messages>

<evidence_pack>
Current-turn RAG/MCP evidence. This is the only factual news source.
</evidence_pack>
```

## Consequences

Positive:

```text
Follow-up questions can resolve pronouns and topics.
User constraints such as brief answer, max chars, and citations continue across turns.
Longer sessions are bounded before model input grows too large.
No RAG collection or frontend API changes are required.
```

Tradeoffs:

```text
v1 summary is deterministic and shallow, not LLM-quality summarization.
Long-term memory is limited to in-session preferences and remains disabled for persistence.
Real factual grounding still depends on current-turn retrieval quality.
```

## Non-goals

```text
No stock prediction.
No investment advice.
No new RAG collection.
No index rebuild.
No Validator enforce expansion.
No LLM-as-judge.
No memory-as-evidence behavior.
```

## Rollback

Use:

```env
CONTEXT_MANAGER_ENABLED=false
SESSION_SUMMARY_ENABLED=false
LONG_TERM_MEMORY_ENABLED=false
```

Rollback does not require schema changes, collection changes, or frontend changes.
