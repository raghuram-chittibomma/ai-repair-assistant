# ADR-0010: Retrieval filters by applicability before authority boosts

## Status

**Interim** — accepted as a working baseline pending the retrieval bake-off
(charter deviation [D4](../CHARTER.md#deviations-from-this-charter)). A later ADR
will supersede this once lexical / hybrid / fusion experiments land.
## Context

Phase 3 stores chunk embeddings in Postgres/pgvector. Semantic similarity alone
fails two corpus-grounded cases from `evals/scenarios/candidates.yaml`:

1. **Wrong platform** — TSP W11395614 can outrank applicable literature for a
   “door locks / won’t run” question on WFW5620HW0, yet must not be cited.
2. **Bulletin over manual** — TSP W11375982 corrects the service manual; naive
   similarity prefers the longer manual.

## Decision

1. **Retrieve with the same local embedder as ingest** (`BAAI/bge-base-en-v1.5`,
   ADR-0009). Query and corpus vectors must use one model.
2. **Over-fetch** cosine neighbours (`--overfetch`, default 40), then **drop**
   hits whose manifest entry fails `document_applies` for the stated appliance.
3. **Light deterministic boosts** (not an LLM): correcting/superseding
   relationships, service-pointer tiers, and error-code token overlap with the
   query. Final order is `similarity + boost`.
4. **CLI:** `repair-corpus search "…" --model WFW5620HW0` for interactive checks.
   Full scenario grading remains a later eval harness.

**Charter deviation:** [D4](../CHARTER.md#deviations-from-this-charter) — interim
baseline before the charter’s retrieval bake-off (lexical / hybrid / rerank).

## Consequences

- Retrieval without `--model` returns pure vector neighbours (dev/debug only).
- Boosts are small so they re-order close candidates; they do not resurrect
  filtered documents.
- Precedence is not yet a full graph walk; only direct `corrects` /
  `supersedes` / `overrides` edges and pointer tiers are used.
