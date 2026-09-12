# ADR-0036: Show source page rasters in the chat UI

## Status

Accepted. Supersedes decision 5 of [ADR-0035](0035-late-fusion-page-images.md)
(UI thumbnails out of scope). Does not change retrieval, gating, or claim
groundedness.

## Context

ADR-0035 already rasters the cited PDF page and sends it to the vision model.
The chat UI then showed only the prose answer and citation labels. When the
model misreads a connector, pin, or drawing, the operator has no page to
compare against.

The JPEG is already on disk under `corpus/parsed/<doc_id>/page-rasters/`
(gitignored). Serving that same file is cheaper than a second render and
keeps the UI and the model looking at one page.

## Decision

1. **Ask and diagnose** return `figure_pages: [{index, doc_id, page, url}]`
   on the JSON body and on the stream `done` event.
2. **`GET /v1/documents/{doc_id}/pages/{page}/image`** serves the cached
   JPEG (`inline`). `doc_id` is restricted to `[A-Za-z0-9][A-Za-z0-9._-]*`.
   Unknown or missing pages are 404. The route uses the same API-key rule
   as the rest of `/v1` (empty key on loopback).
3. **`/ui`** renders each attached page under the answer, with a caption
   that the model may misread the drawing. Click opens the JPEG in a new
   tab. Chat export lists the page URL, not bytes.
4. **Traces still omit JPEG / data-URL bytes** (ADR-0035).

## Consequences

- The operator can cross-check the graphic without opening the PDF.
- `<img src>` does not send `X-API-Key`. Loopback with an empty
  `REPAIR_API_KEY` is the supported UI path (D8 / ADR-0025).
- Manufacturer page rasters stay out of git.
