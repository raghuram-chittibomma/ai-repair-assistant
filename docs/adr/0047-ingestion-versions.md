# ADR-0047: Per-document ingestion strategy over versioned derived data

## Status

Accepted. Extends [ADR-0008](0008-incremental-ingestion.md) (fingerprint skip
and schema stay in force). Does **not** change the default chunker: structured
table-row chunking ([ADR-0007](0007-parser-and-chunker.md),
[ADR-0022](0022-contextual-chunk-enrichment.md)) remains the path for every
document. Enables [ADR-0048](0048-semantic-knowledge-units.md).

## Context

We want to experiment with LLM semantic chunking on a few high-value manuals
without disturbing the other 21 documents. Today `chunks` rows are the only
representation a document can have: `replace_chunks` deletes the old set and
writes the new one, so re-processing a document under a second strategy would
either destroy the working representation or double-index it.

Two things must be true at once. A promoted document must keep serving its
legacy chunks while a human reviews the proposal, and the instant the semantic
version goes live the legacy rows must stop reaching vector search, the lexical
and literal arms, `code_fetch`, the sibling expansion, and generation.

## Options

| | A — Replace the chunker globally | B — Per-document strategy over versioned derived data | C — Index both, always |
| --- | --- | --- | --- |
| Other 21 docs unaffected | No | Yes | Yes |
| Duplicate active retrieval | No | No | **Yes** |
| Legacy stays live during review | n/a | Yes | Yes |
| Rollback / re-segment without data loss | No | Yes | Yes |
| Retrieval SQL changes | None | One view swap | Every arm needs a strategy filter |
| Choice | Rejected — structured chunking wins the current bake-offs | **Accepted** | Rejected — the duplicate-retrieval failure the requirement names |

## Decision

1. **`ingestion_versions` is the unit of derived data.** One row per
   `(doc_id, version)` carrying `strategy` (`structured` | `semantic_llm`) and
   `status` (`candidate` | `ready` | `active` | `superseded` | `abandoned`).
   Every `chunks` row belongs to exactly one version.
2. **One active version per document, enforced by the database.** A partial
   unique index on `(doc_id) WHERE status = 'active'` makes a duplicate active
   representation unrepresentable rather than merely unlikely.
3. **Retrieval reads the `active_chunks` view, never `chunks`.** Invalidation is
   therefore one fact in one place. Superseded rows stay stored for audit and
   comparison; they are simply not in the view.
4. **Cutover is one transaction**: the incoming version becomes `active` while
   the outgoing one becomes `superseded` with `superseded_by` set. There is no
   window where a document has no active version, and a failed or abandoned
   proposal leaves the legacy version untouched.
5. **Logical invalidation, not deletion.** Reverting to an earlier version is
   an activation, not a re-parse. The source PDF and `corpus/parsed/` are never
   written by any of this.
6. **`repair-corpus ingest` owns the `structured` version only.** It refuses to
   overwrite chunks belonging to an active non-`structured` version, so routine
   re-ingest of the corpus cannot clobber a reviewed semantic document.
7. **Every hit carries its strategy.** That is the metadata a later evaluation
   mode would need to compare strategies. Simultaneous dual-active retrieval is
   not built here.

## Consequences

- Migration `003` backfills one `structured`/`active` version per existing
  document and stamps its chunks, so retrieval behaviour is unchanged the moment
  the migration lands. `bench-retrieve` must confirm that.
- `chunks` gains three nullable columns. Legacy rows keep `unit_id` and
  `rep_kind` NULL, which is what makes the semantic path additive.
- The view is a simple join, so Postgres inlines it and the HNSW and trigram
  indexes still apply. Measured by the existing retrieval fixtures, not by
  assertion.
- Storage grows: a promoted document keeps both representations. Acceptable for
  a 22-document corpus; a prune command is a later concern if it stops being.
