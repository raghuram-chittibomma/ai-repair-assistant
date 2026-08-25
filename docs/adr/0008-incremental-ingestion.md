# ADR-0008: Incremental ingestion into Postgres + pgvector

## Status

Accepted — **embedding provider superseded by [ADR-0009](0009-local-open-embeddings.md)**
(schema and incremental rules here remain in force).

## Context

Phase 2 writes structured chunks under `corpus/parsed/<doc_id>/` (JSONL +
`meta.json`). Phase 3 must load those chunks into PostgreSQL with pgvector so
later retrieval can query them, without re-inventing extraction (ADR-0007) and
without committing manufacturer text.

Constraints already decided: PostgreSQL + pgvector, Docker on a shared LAN host
(ADR-0006), OpenAI for **LLM inference only** (embeddings: see ADR-0009),
incremental refresh when documents revise.

## Decision

1. **Source of truth for bytes in the DB:** `corpus/parsed/` only. Ingest never
   re-parses PDFs; operators re-run `repair-corpus parse` when extractors or
   documents change, then ingest.
2. **Schema:** `documents` (one row per `doc_id`) and `chunks` (one row per
   parser `chunk_id`, FK cascade). Chunk rows store text, page, kind,
   `error_codes`, language, publication/revision, JSON metadata, and an optional
   `embedding vector(768)` (see ADR-0009).
3. **Change detection:** each parsed document has a `content_fingerprint` =
   SHA-256 over sorted `chunk_id:content_hash` pairs. Unchanged fingerprint →
   skip upsert. Unchanged individual `content_hash` → keep existing embedding.
4. **Embeddings:** local open-source model — **see ADR-0009** (not OpenAI).
   `repair-corpus ingest --skip-embed` loads text without running the encoder.
5. **Runtime config:** `DATABASE_URL` and Compose vars live in `.env.local`
   (gitignored). Committed `.env.example` and `docker/compose.yaml` use
   placeholders only. OpenAI keys are not required for ingest.
6. **Near-duplicate pages across revisions:** store `content_hash` and index it;
   retrieval-time dedup / revision precedence remain Phase 4+ concerns. Ingest
   does not collapse cross-document near-duplicates.

**Charter deviation:** [D5](../CHARTER.md#deviations-from-this-charter) —
per-chunk hash skip is in place; full structural/element-level change detection
is not.

## Consequences

- Operators need a reachable Postgres with the `vector` extension
  (`pgvector/pgvector:pg17` via Compose).
- Embedding cost is local compute only (ADR-0009); `--skip-embed` isolates DB work.
- Re-parsing that changes chunk ids or hashes forces re-embed of affected rows.
- Applicability filtering still uses the manifest at query time; the DB stores
  document identity fields for citation, not full applicability trees yet.
