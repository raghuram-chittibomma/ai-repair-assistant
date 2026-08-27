# ADR-0007: Parser and chunker selection

## Status

Accepted

## Context

Phase 1 showed that naive text extraction of Whirlpool tech sheets scrambles
tables and that blank-line / fixed-size chunking severs error codes from their
remedies. Parser choice therefore had to be made on fixtures, not by library
default.

Candidates scored locally against `evals/parsing/fixtures.yaml`:

| Extractor | Strategy | `error-codes-bound` | Notes |
| --- | --- | --- | --- |
| pypdf | naive_fixed (control) | **FAIL** (F6E1 unbound) | Full-text finds codes; fixed windows orphan F6E1 from Test #2 |
| pdfplumber | structured table rows | **PASS** | Error table rows bind code + problem + checks |
| pymupdf | structured table rows | **PASS** | Equivalent binding on the same table |

Both pdfplumber and pymupdf clear the hard fixtures (`error-codes-bound`,
`pua-list-markers`, near-dup stability, reflow-not-delta, TSP languages,
MHTML decode). Scorecard: `evals/parsing/results/scorecard.md`.

## Decision

1. **Default PDF extractor: `pdfplumber`.** Table extraction is the primary
   reason tech sheets become usable; pdfplumber’s table API is the simpler
   dependency surface for that job. PyMuPDF remains an available alternate
   (`repair-corpus parse --extractor pymupdf`) when layout blocks matter more
   than tables.
2. **Chunking: structured.** Prefer one chunk per error-code table row with
   `error_codes` metadata; prose uses heading-aware sections. Never use
   blank-line-only or fixed-size windows as the production strategy.
3. **PUA list markers:** map U+F0D8 / U+F06E to bullets before splitting lists
   (`repair_assistant.parsing.pua`).
4. **MHTML:** MIME-decode and rejoin quoted-printable soft breaks before any
   HTML text use (`repair_assistant.parsing.mhtml`).
5. **Preserve manufacturer typos** in extracted text (citation fidelity /
   hash verification).

**Charter deviations:** [D2](../CHARTER.md#deviations-from-this-charter) (chunking
folded into parse phase), [D3](../CHARTER.md#deviations-from-this-charter)
(chosen on parsing fixtures, not yet retrieval end-to-end evals).

## Consequences

- `repair-corpus parse` writes `corpus/parsed/<doc_id>/chunks.jsonl` (gitignored).
- `repair-corpus bench-parse` re-runs the bake-off; CI unit tests cover helpers
  and synthetic PDFs without requiring the manufacturer corpus.
- Phase 3 ingestion must read these chunks (or re-parse with the same defaults),
  not invent a second extraction path.
- **Follow-on (ADR-0022):** contextual enrichment of chunk text (doc/section/table
  headers) plus a bounded audit→repair→re-audit quality gate; split boundaries
  unchanged.
- pypdf remains for identity/metadata only in the corpus package; content
  extraction goes through the parsing package.
- **Follow-on (2026-08-26):** optional experimental extractor `docling`
  (`pip install -e ".[docling]"`, `parse`/`bench-parse --extractor docling`)
  matched pdfplumber/pymupdf on all parse fixtures but is **not** the default
  (heavy local ML models, much slower). See
  [DOCLING_GRAPHRAG_EVAL.md](../corpus/DOCLING_GRAPHRAG_EVAL.md).
