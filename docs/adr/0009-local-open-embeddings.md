# ADR-0009: Local open-source embeddings (no paid embed API)

## Status

Accepted (supersedes the embedding choice in ADR-0008)

## Context

ADR-0008 selected OpenAI `text-embedding-3-small` because the charter lists
OpenAI among fixed technologies. The operator constraint is stricter: **the only
paid cloud cost this project may incur is OpenAI LLM inference.** Embeddings
must be free and open-source.

## Decision

1. **Default embedder: `BAAI/bge-base-en-v1.5`** via `sentence-transformers`,
   run on the ingest workstation. MIT license, open weights, 768 dimensions,
   strong English retrieval on MTEB — a common production OSS RAG default and a
   practical peer to `text-embedding-3-small` for short repair chunks.
2. **Store as `vector(768)`** in Postgres/pgvector; L2-normalize at encode time
   so cosine distance is well-defined.
3. **No OpenAI (or other paid) calls during ingest.** `OPENAI_API_KEY` is not
   required for Phase 3. OpenAI remains for later LLM graph nodes only.
4. **Override:** `EMBEDDING_MODEL` / `EMBEDDING_DIMS` in `.env.local` if an
   operator swaps models (changing dims requires a schema migration).
5. **Known limit:** `bge-base-en-v1.5` is English-primary. Bilingual FR/EN TSP
   pages in this corpus are secondary; if FR retrieval quality becomes an eval
   failure, revisit `BAAI/bge-m3` (heavier, multilingual) in a new ADR.

**Charter deviation:** [D1](../CHARTER.md#deviations-from-this-charter) — OpenAI
is not used for embeddings.

## Consequences

- First ingest downloads ~400MB of weights to the local Hugging Face cache
  (one-time; free). Subsequent runs are offline.
- Workstation CPU/GPU does the embedding work; Postgres only stores vectors.
- Any DB already created with `vector(1536)` must be rebuilt or migrated before
  ingest (Phase 3 had not been smoked on a live DB when this ADR landed).
- Retrieval (Phase 4+) must use the same model for queries; BGE-v1.5 works
  without a query instruction prefix for convenience (optional instruction
  documented by BAAI remains available).
