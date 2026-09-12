# ADR-0035: Gated late-fusion page images at generate time

## Status

Accepted — review R33 follow-on. Does **not** supersede [ADR-0009](0009-local-open-embeddings.md).
Decision 5 (UI thumbnails out of scope) is superseded by
[ADR-0036](0036-ui-source-page-images.md).

## Context

Figure and wiring pages are classified and their OCR prose is not indexed
(R33). Ask/diagnose then inject
`Note: this assistant cannot read figures or wiring diagrams` when a hit
cites a figure. That is honest and still leaves the graphic unused.

Captioning diagrams at chunk time would write a VLM's words into the index.
Image embeddings (CLIP / ColPali) would reopen the embedder and ranking.

The LLM already accepts images. Retrieval already returns `doc_id` + PDF
page. The missing piece is attaching the **page raster** when a hit is a
figure, schematic, photo-access page, or cites an unread figure.

## Decision

1. **Retrieval stays text.** `vector_apply_boost` and local
   `BAAI/bge-base-en-v1.5` are unchanged. No image bytes in Postgres.
2. **Late fusion, gated.** After search, attach at most three unique
   `(doc_id, page)` JPEGs (~150 dpi, pymupdf) when the hit text looks like
   a figure / schematic / photo-access page or `evidence_cites_unread_figure`.
   Cache under `corpus/parsed/<doc_id>/page-rasters/` (gitignored).
3. **Missing PDF or no vision model:** keep the unread-figure note. Do not
   invent a floating model alias. `LLM_VISION_MODEL` is an optional dated
   snapshot; if unset, reuse `LLM_MODEL` only when it is vision-capable.
4. **Claims stay text-bound** ([ADR-0029](0029-claim-groundedness.md)).
   Images are for location / orientation / which part in the photo. Do not
   invent pin numbers, voltages, or hold times from the picture alone.
5. **Ask and diagnose** both attach gated images. UI display of those
   rasters is [ADR-0036](0036-ui-source-page-images.md) (this ADR originally
   left thumbnails out of scope).

## Reopen (not this ADR)

Image embeddings only if, after this slice and mixed-page text cleanup,
figure-only sheets still never appear in the hit list. That is a new ADR
and a new vector column — not a silent embedder swap.

## Consequences

- Generate tokens and latency rise on figure-citing turns only.
- Traces must not store raw JPEG / data-URL bytes.
- Live check (not CI): a drain-filter / DVT / wiring cite attaches a raster
  and still cites `[n]` without invented pin text.
