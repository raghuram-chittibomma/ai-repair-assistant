# ADR-0049: PDF-native semantic boundaries

## Status

Accepted. **Partially superseded** by [ADR-0050](0050-generate-hybrid-pdf-evidence.md)
for generate-time attachments (decision 5’s “generation reads only
`source_text`”). Boundaries, thin `source_text`, and curator modality remain.

## Context

ADR-0048 had the segmentation model pick parsed `chunk_id` anchors and assemble
`source_text` from hybrid-parse bodies. That put a parser/chunker in the middle
of the curator path and made the review UI annotate page rasters of parsed
bboxes rather than the manufacturer PDF. The product intent is: send the real
PDF (or page images when the file is a scan), propose page-range markers,
reviewers drag those markers on the PDF, and RAG generation cites the verbatim
PDF span — not enriched parse text.

## Options

Segmentation input:

| | A — Native PDF file | B — Page rasters (vision) | C — Thin text extract only | A+B hybrid |
| --- | --- | --- | --- | --- |
| Matches “send the actual PDF” | Yes | Visual only | No | Yes |
| Works for scanned manuals | Weak | Yes | Fails | Yes |
| Cost / ops complexity | Medium | High | Low | Medium |
| Choice | — | — | Rejected as primary | **Accepted** |

## Decision

1. **Boundaries are PDF page ranges**, not parsed anchors. A proposal unit is
   `{start_page, end_page, start_y?, end_y?, title, unit_type, …}` with pages
   1-based inclusive and optional `[0,1]` page-fraction offsets for drag
   handles.
2. **Modality is A+B.** Text PDFs: send native PDF parts to the model (split
   by outline/bookmarks when large, else fixed page windows). When
   `FileFacts.looks_scanned` (or an operator override), send page rasters via
   the existing vision path. The hybrid parser is not on the segmentation path.
3. **`source_text` is a thin PDF extract** of the unit’s page range (pymupdf
   page text only — no hybrid parse, no contextual enrichment). Empty extract
   on a scanned unit sets `needs_ocr` and blocks activate until OCR exists;
   do not backfill from parsed JSONL.
4. **Validation is page coverage**, not anchor membership: pages in bounds,
   ordered, no overlap, full coverage of the window the model was given.
5. **Representations still carry search vectors** (overview / facts /
   questions) after boundaries are approved. Generation keeps `source_text` in
   the evidence pack for citations; **layout attachments** (native PDF
   page-range or rasters when scanned) are ADR-0050. Structured and semantic
   docs may mix in one corpus via ADR-0047 (one active version per `doc_id`).
6. **Review UI shows the real PDF** (PDF.js) with draggable markers. Compare
   against a prior version’s markers is deferred (nice-to-have).

## Consequences

- OpenAI client gains a curator-only PDF file path; diagnose ingest stays
  free of paid calls and free of PDF upload.
- Existing parsed-anchor semantic proposals are obsolete; re-propose under
  this ADR.
- Scanned manuals can be segmented visually but cannot activate for RAG until
  an OCR slice supplies non-empty `source_text`.
- Charter D9 (paid curator LLM) still applies; modality choice may increase
  token cost on large or scanned manuals.

## See also

[architecture/08 — Semantic curator → generate](../architecture/08-semantic-curator-to-generate.md) · [ADR-0050](0050-generate-hybrid-pdf-evidence.md) · [ADR-0051](0051-pdf-primary-semantic-evidence.md)
