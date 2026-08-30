# ADR-0013: LangGraph multi-turn diagnostic assistant

## Status

Accepted

## Context

Phase 5 delivers one-shot grounded Q&A via `repair-corpus ask`
([ADR-0012](0012-grounded-qa.md)). Charter Phase 7 requires evolving that into
interactive troubleshooting with explicit diagnostic state and multi-turn eval
cases that verify trajectory, not only final wording.

LangGraph is a fixed technology in the charter. Safety policy, full answer
eval harness, and product hardening remain later phases.

## Decision

1. **Graph per turn:** a small LangGraph workflow runs on each user message:
   `retrieve → respond`. The CLI/session holds conversation history between
   turns.
2. **State:** `DiagnosticGraphState` tracks messages, appliance context,
   retrieval query, evidence text, citation pool, and abstention flags.
3. **Retrieval:** reuse ADR-0010 `search()`. The diagnose query is built from
   user turns: acknowledgement-only messages are omitted; a later mid-cycle /
   no-code stop replaces a vague first-turn anchor so search does not stay on
   the original symptom chapter; session error codes are prepended.
4. **Generation:** OpenAI chat with a multi-turn system prompt; same citation
   `[1]` / `[2]` convention and `ABSTAIN:` handling as Phase 5.
5. **CLI:** `repair-corpus diagnose --model WFW5620HW0` — interactive REPL, or
   pass one message for a single turn.
6. **Smoke evals:** `evals/qa/smoke-scenarios.yaml` for hand-run regression
   until Phase 9 automated answer grading exists.

**Charter alignment:** implements Phase 7 (README Phase 6). No new deviations.

## Consequences

- Requires `langgraph` and `langchain-core` in addition to OpenAI.
- Session state is in-process only; persistence/API layers are deferred.
- Multi-turn eval fixtures are recorded but not yet automated in CI.
- Safety/escalation rules are still prompt-level, not deterministic policy.
