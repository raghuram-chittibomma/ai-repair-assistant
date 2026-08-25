# ADR-0012: Grounded repair Q&A via retrieval + OpenAI chat

## Status

Accepted

## Context

Phase 4 delivers `repair-corpus search` with applicability filtering and light
boosts ([ADR-0010](0010-retrieval-applicability.md)). Charter Phase 6 requires
grounded answers with provenance, citations, and abstention when evidence is
insufficient.

OpenAI is reserved for LLM inference only ([ADR-0009](0009-local-open-embeddings.md),
charter deviation D1). LangGraph multi-turn diagnostics and full answer eval
harnesses are explicitly later phases.

## Decision

1. **Pipeline:** reuse the ADR-0010 retrieval path (`search()`), format top hits
   as numbered evidence blocks, then call OpenAI chat completion.
2. **CLI:** `repair-corpus ask "…" --model WFW5620HW0` — same appliance
   context as `search`.
3. **Model:** default `gpt-4o-mini` via `LLM_MODEL`; temperature 0.2.
4. **Citations:** the model cites evidence as `[1]`, `[2]`, …; the CLI maps
   those back to `doc_id` / `chunk_id` / publication label.
5. **Abstention:**
   - skip the LLM when retrieval returns zero applicable hits;
   - instruct the model to reply `ABSTAIN: …` when evidence is insufficient;
   - surface abstention clearly in CLI output.
6. **Tests:** unit tests for evidence formatting and citation parsing with a
   mock LLM client — no live OpenAI calls in CI.

**Charter alignment:** implements Phase 6 (README Phase 5). No new deviations.

## Consequences

- Requires `OPENAI_API_KEY` in `.env.local`; missing key fails fast with a
  clear error.
- Answer quality is not yet graded; retrieval bake-off remains separate
  ([ADR-0011](0011-retrieval-bakeoff.md)).
- Safety policy and escalation rules are deferred to charter Phase 8.
- Each `ask` call incurs OpenAI usage; retrieval still uses free local BGE.
