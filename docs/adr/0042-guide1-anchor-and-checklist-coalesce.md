# ADR-0042: Guide #1 title-case anchors and one-citation checklists

## Status

Accepted. Supersedes the ALL-CAPS-only Guide #1 clause in
[ADR-0022](0022-contextual-chunk-enrichment.md) decision 6. Does not
change `vector_apply_boost`, ranking R11 / R20 / R22, or diagnose
retrieve labels ([ADR-0039](0039-diagnose-retrieve-labels.md)).

## Context

Live diagnose on `door doesn't open` retrieved the right **Door Won't
Unlock** table but cited one cause row. The page JPEG showed three
rows; `[n]` text was only reset/unplug. The model drip-fed that first
remedy, then hopped books.

Two mechanical gaps:

1. **Service-manual Guide #1 is title case** (`Door Won't Unlock`).
   ADR-0022 required an ALL-CAPS first line, so empty problem cells
   (latch, See TEST #4) did not inherit `problem_title`. Those rows
   never joined the hit.
2. **Search returns one row.** Even after inherit works, rank can
   surface the latch or TEST #4 line. The prompt already says present
   every check for one category in a single turn, but it can only
   quote what is in `[n]`.

Tech-sheet pages that miss `find_tables()` still need a unique
word-span box ([ADR-0038](0038-paragraph-highlight.md)). A coalesced
hit that copies the first row's metadata and drops `page_width` shows
the page with no overlay.

## Options

| | A — Prompt the model to invent the other rows from the JPEG | B — New ranking constant for “first row” | C — Inherit title-case anchors; expand + coalesce same-problem rows |
| --- | --- | --- | --- |
| Stays inside quoted text | No (ADR-0035) | Yes | Yes |
| Extra ranking fit to 14 hard fixtures | No | Yes | No |
| `[n]` is the on-page checklist | No | Maybe | Yes |
| Choice | Rejected | Rejected | **Accepted** |

## Decision

1. **Guide #1 anchors are OEM problem names, not ALL-CAPS only.**
   `Door Won't Unlock`, `Won't Dispense`, `Overfills`, `Motor Overheats`
   count. Strip a trailing parenthetical before the test. Cause
   sentences with `.` / `!` / `?` (`Door lock mechanism not
   functioning.`) are not anchors. Guide #2 group titles
   (`POOR WASH PERFORMANCE`) stay rejected.
2. **After rank, fill same-page siblings** that share exact
   `metadata.problem_title`. Sort first remedies (reset / unplug /
   door fully closed) ahead of other causes, then `See TEST #N`.
3. **Coalesce those siblings into one evidence hit** so `[n]` lists
   every cause/check pair for that problem. Union unique bboxes. Copy
   `page_width` / `page_height` / `bbox_space` from any sibling that
   has them so `/ui` can overlay. This is retrieve *formatting*, not
   a new boost.
4. **Prose-fallback table rows** (no `find_tables()` grid) may box
   unique short cause/check cells and union them
   ([ADR-0038](0038-paragraph-highlight.md)). Duplicate phrases
   (`See TEST #4` on lock and unlock) stay unboxed.
5. **Re-parse + re-ingest** is required before live chunks pick up
   inherited titles or new boxes. PDFs stay out of git.

## Consequences

- Diagnose can walk the full Door Won't Unlock category from one
  citation. Ack/unresolved protocol (board + `acks.py`) still decides
  whether to advance or close; this ADR does not add a flowchart.
- Service-manual p.35 and tech-sheet Guide #1 pages must be re-parsed
  after this change. Empty `problem_title` rows cannot expand.
- Retrieval / BGE / `vector_apply_boost` are unchanged.
