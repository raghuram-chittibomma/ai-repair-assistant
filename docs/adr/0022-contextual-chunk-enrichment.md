# ADR-0022: Contextual chunk enrichment and bounded quality self-check

## Status

Accepted

## Context

ADR-0007 selected **pdfplumber + structured table-row chunking**. That binding
path is correct for error-code tables, but chunk **text** often lacked
positional ancestry (document title, section heading, table column headers).
Numeric lookup rows therefore embedded as bare values like `14 | -10 | 111.6`,
which hurt semantic retrieval and LLM evidence (observed in Langfuse retrieval
audits). Table headers already lived in `metadata.headers` but were never
concatenated into the string used for embeddings or `format_evidence`.

Charter lists hierarchical / contextual chunking as candidates. E12 deferred a
full chunking micro-bake; opaque numeric rows justify a **thin reopen**: enrich
in place and gate with a **bounded** audit→repair→re-audit (not a while-loop,
not a blind re-splitter).

## Decision

1. **Keep ADR-0007 split boundaries** (one table row per chunk; heading-aware
   prose). Do not switch the default to fixed-size or naive recursive splits.
2. **Enrich `chunk.text`** at chunk time with document label, nearest section
   title, and table headers (keyed `Header: value` when counts match).
3. Store ancestry in metadata (`doc_title`, `doc_type`, `section_path`,
   `headers`, `body_text`) so repairs stay idempotent.
4. After enrich, run **`audit_and_improve`**: audit → at most **one** repair
   pass → re-audit → always stop (`MAX_REPAIR_PASSES = 1`). Flag-only findings
   never auto-merge body text. Persist `chunk_quality.json` beside
   `chunks.jsonl`.
5. LLM header suggestions and Langfuse watchlists are **offline / explicit**
   only — never chained from ask/diagnose into re-parse.

## Consequences

- Re-parse changes `text` / `content_hash` → re-embed (ADR-0008).
- Error-code binding fixtures must remain PASS.
- Extends ADR-0007; does not supersede extractor choice.
- E12: thin reopen for contextual enrichment + quality gate (see
  [EVAL_FRAMEWORK_GAPS.md](../EVAL_FRAMEWORK_GAPS.md)).
