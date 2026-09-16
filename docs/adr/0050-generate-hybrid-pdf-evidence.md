# ADR-0050: Hybrid PDF evidence at generate time

## Status

Accepted. **Supersedes** [ADR-0049](0049-pdf-native-semantic-boundaries.md)
decision 5’s claim that generation reads only `source_text`, and removes the
structured 2 000-character evidence `_excerpt` from [ADR-0048](0048-semantic-knowledge-units.md)
decision 1’s legacy path. Keeps ADR-0049 boundaries, thin `source_text` for
citations/claim-binding, and curator modality.

## Context

Semantic units are retrieved via compact representations, then collapsed to
unit `source_text` for the evidence pack. That text is a thin PDF extract — it
does not restore tables, figures, or page layout the technician sees. ADR-0049
already chose native PDF vs page rasters for **segmentation**; generation still
sent text only. Separately, structured chunks were windowed to ~2 000 characters
at generate time, which could drop the remainder of a procedure after a large
semantic unit filled the pack budget.

## Decision

1. **Semantic generate attachments are hybrid (A+B).** For each cited semantic
   unit, inspect the manufacturer PDF (`FileFacts.looks_scanned`):
   - text PDF → slice the unit page range with `write_pdf_part` and attach as
     OpenAI file part(s);
   - scanned → attach page rasters for pages in the unit range (capped by
     `REPAIR_SEMANTIC_EVIDENCE_MAX_PAGES`, default 8).
2. **`source_text` stays in the fenced evidence pack** for citations, UI
   labels, and claim grounding. PDF/rasters are additional layout authority.
3. **Structured chunks send full stored text** — no per-hit 2 000-character
   excerpt. Pack-level `REPAIR_EVIDENCE_MAX_CHARS` (unset/`0` = unlimited) and
   retrieval top‑N remain the only size gates.
4. **Streaming:** when any native PDF file part is attached, ask/diagnose use
   non-stream `complete` for that turn. Raster-only turns keep streaming.

## Consequences

- Generate cost rises when semantic units are cited (file upload or multiple
  rasters).
- Ask streaming may pause as a single buffered answer when a text semantic PDF
  is attached.
- Temp PDF slices are deleted after the generate call.
- Langfuse generate observations attach the same page-range PDF bytes via
  ``LangfuseMedia`` (`native_pdf_parts`) so the UI can show the file that went
  to the model (self-hosted media/S3 required; OEM content stays LAN-only).
- Curator segmentation path unchanged.
