# ADR-0037: Table-row highlight on source page images

## Status

Accepted. Extends [ADR-0036](0036-ui-source-page-images.md) (page JPEG in
`/ui`). Does not change retrieval, embeddings, or claim groundedness.

## Context

ADR-0036 shows the cited PDF page so the operator can cross-check a drawing.
Dense tech-sheet tables still require hunting for the row that grounded `[n]`.
Parse models already have `BBox` on `TableRow`, but the hybrid extractor
(`extract_tables()`) keeps text only.

A guessed crop on a wiring page would look authoritative and still be wrong.
Table rows are the case where pdfplumber has a real rectangle.

## Decision

1. **Keep `extract_tables()` as the table-text source** ([ADR-0024](0024-hybrid-parse-architecture.md)).
   Do not switch the default to `find_tables()` for cell strings.
2. **Attach geometry by unique row-text match.** After extract, call
   `find_tables()`, match normalized cell strings, and set `TableRow.bbox` only
   when exactly one found row matches. No match → no box.
3. **Persist on the chunk, not the embed.** `metadata.bbox` plus
   `page_width` / `page_height` / `bbox_space: pdfplumber_pt`.
   `content_hash` stays text-only. Ingest upserts metadata when the text
   fingerprint is unchanged so a bbox-only re-parse does not re-embed.
4. **Citations are links.** Every cite with `doc_id` + `page` gets
   `url` for `GET /v1/documents/{doc_id}/pages/{page}/image`. Optional
   `bbox` + page size when the chunk is a matched `table_row`.
5. **`/ui`** turns `[n]` and the citation list into links. Click scrolls
   to the page JPEG and draws an overlay when `bbox` is present. No crop.
   Figure / schematic / photo-access cites stay full-page (no invented box).
6. **Traces store numbers and URLs only** — not JPEG bytes ([ADR-0035](0035-late-fusion-page-images.md)).

## Consequences

- Operator can land on the error-table row that grounded a claim.
- Re-parse of the local corpus is required before live chunks have boxes.
  PDFs and rasters stay out of git.
- Ambiguous or mismatched rows show the page without a highlight.
- Retrieval / BGE / `vector_apply_boost` are unchanged.
