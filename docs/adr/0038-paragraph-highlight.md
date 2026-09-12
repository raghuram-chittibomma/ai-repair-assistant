# ADR-0038: Paragraph highlight on source page images

## Status

Accepted. Extends [ADR-0037](0037-table-row-highlight.md). Does not change
retrieval, embeddings, or claim groundedness.

## Context

ADR-0037 overlays a box on a uniquely matched table row. Prose, procedure, and
heading cites still open the page JPEG with no rectangle. Guessing a crop on a
wiring page, or unioning two columns across a gutter, would look authoritative
and still be wrong.

pdfplumber `extract_words()` already has per-word rectangles in the same
`pdfplumber_pt` space as table-row boxes. Hybrid currently stores one page-level
`Block` with no geometry.

## Decision

1. **Keep hybrid text as the chunk source** ([ADR-0024](0024-hybrid-parse-architecture.md)).
   Do not switch prose extraction to PyMuPDF blocks for geometry.
2. **Attach geometry by unique word-span match.** After extract, keep
   `extract_words()` in memory on `ExtractedPage`. Match
   `metadata.body_text` (not the contextual title/pub wrapper). Set a box only
   when the normalized body is a unique contiguous span **and** those words
   form one spatial cluster (x-gap about `0.25 * page_width`). No match,
   two-plus hits, too-short needle, or a two-column smear → no box.
3. **Kinds.** Only `prose`, `procedure`, and `heading`. Do not overwrite a
   `table_row` box. Skip `figure` / `schematic` / `toc` layout kinds.
   `multi_column` / `photo_access` may box when the span is unique and
   one-cluster.
4. **Persist on the chunk, not the embed.** Same keys as ADR-0037:
   `metadata.bbox`, `page_width`, `page_height`, `bbox_space: pdfplumber_pt`.
   Word lists stay in-memory during parse and are not written to `chunks.jsonl`.
5. **API / UI unchanged.** One optional bbox per citation; `/ui` already draws
   the overlay. KB/MHTML stays page-less.
6. **Traces store numbers and URLs only** — not JPEG bytes ([ADR-0035](0035-late-fusion-page-images.md)).

## Consequences

- Operator can land on the procedure or paragraph that grounded a claim when
  the span is unique and one-column.
- Re-parse of the local corpus is required before live prose chunks have boxes.
  PDFs and rasters stay out of git.
- Repeated boilerplate (`NOTE`, `WARNING`) and two-column smears stay page-only.
- Troubleshooting rows that come from the prose fallback (no `find_tables()`
  grid) may use the same unique word-span when no table box exists. Cause and
  check cells may be shorter than the prose minimum; a row may union those
  unique cells even when they sit in adjacent columns. That does not overwrite
  an ADR-0037 table-row box. Same-problem retrieve hits copy `page_width` /
  `page_height` from a sibling so a coalesced checklist still overlays
  ([ADR-0042](0042-guide1-anchor-and-checklist-coalesce.md)).
- Retrieval / BGE / `vector_apply_boost` are unchanged.
