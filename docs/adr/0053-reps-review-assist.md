# ADR-0053: Reps review UI + specialist assist

- **Status:** Accepted
- **Date:** 2026-09-20

## Context

After Propose, curators settle PDF-native unit boundaries on `/ui/corpus`, then
**Finalize** generates retrieval representations (`overview` / `facts` /
`questions`) and marks the version `ready`. Activate cutover still required
human confidence in those reps, but the board only showed markers — editing
needed raw API calls. Assist can help rewrite reps without becoming an
auto-writer on the live corpus.

## Decision

1. **Same board, second phase.** After Finalize (version `ready`, or when units
   already carry representations), `/ui/corpus` offers a **Review reps** mode
   beside **Boundaries**. Stage CTAs stay singular (Propose → Finalize →
   Activate); only the next primary action is solid blue.
2. **Chunk-focused PDF.** In Review reps the PDF pane shows **only** the
   selected unit’s page span (y-clipped). Collapsible PDF rail (‹ / ›) frees
   horizontal space for the editor; docs list stays hidden in this mode.
3. **Stacked work area.** Right column: reps editor on top (overview / facts /
   questions), Assist below. Apply / Clear sit with the suggest reply; Send
   stays with the compose box. Panels are resizable.
4. **Suggest-only specialist assist.** In-memory sessions (TTL / max, **410** when
   unknown — same pattern as diagnose sessions, ADR-0021) under
   `/v1/corpus/.../assist/*`. The model returns draft overview/facts/questions
   plus a short rationale. **Apply** fills the editor only; **Save** still
   requires an explicit PATCH. The assistant never writes the DB or Activates.
5. **PDF-primary assist context.** Each assist turn attaches the unit’s native
   PDF page-range (or page rasters when scanned) plus document/unit metadata,
   matching generate’s PDF-primary stance (ADR-0051).

## Consequences

- Curator flow becomes: Propose → marker review → Finalize → **Review reps (+
  assist)** → Activate.
- Langfuse roots name `corpus_assist` with `doc_id`, `unit_key`, session id.
- Assist uses `SEMANTIC_OPENAI_API_KEY` (same curator key as Propose).
- No R41 feedback UI; no persistence of assist sessions across API restart.

## Alternatives considered

- Separate `/ui/corpus/reps` app — rejected; one board keeps PDF + unit context.
- Auto-apply assist JSON to the corpus — rejected; human gate before Save.
- Text-only assist without PDF attach — rejected after measure; layout-heavy
  units need the page-range attachment.
