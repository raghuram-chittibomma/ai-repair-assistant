# ADR-0044: Diagnose session tally is a read-only board view

## Status

Accepted. Extends [ADR-0031](0031-structured-diagnostic-state.md) (inspectable
board) and [ADR-0017](0017-web-ui-deploy-eval.md) (`/ui`). Does not change
retrieve, generate, or ranking. Not [R41](../ARCHITECTURE_REVIEW_RESPONSE.md)
feedback capture. Sessions stay in-memory
([ADR-0021](0021-api-hardening-embedder-sessions.md)).

## Context

The diagnose board already tracks the symptom, cleared checks, and (when set)
the next check. `/ui` ignored that object, so the operator only saw the chat.
After several “checked / no issues” turns it was easy to lose what had been
offered and which `[n]` the session was still on.

ADR-0031 named a repair summary as future work on this board. A clickable
flowchart would reopen [ADR-0034](0034-diagnose-nlu-split.md) (rules own
protocol; no expert-system tree). Thumbs or “did this solve it?” would be R41.

`ruled_out` is a list of strings. Merge also stores short `test #N` needles
for protocol. Those must not appear raw in the product surface. Per-check
`evidence_index` is not on the board; progress follow-ups reuse one pack
([ADR-0043](0043-session-evidence-reuse.md)), so this turn’s (or the pack’s)
first citation is an honest session chip.

## Options

| | A — Chat only | B — Read-only tally from the board | C — Interactive path / persist |
| --- | --- | --- | --- |
| Visibility of cleared checks | Weak | Yes | Yes |
| New protocol | No | No | Flowchart risk |
| Session store | — | In-memory only | Postgres (reopens ADR-0021) |
| Choice | Rejected | **Accepted** | Rejected |

## Decision

1. **`/ui` diagnose mode** shows a session path panel: symptom, cleared
   checks, this turn’s offered checks (from the assistant list), next (or
   “path closed”), and one citation chip for the current pack. Ask and
   Search hide it. The UI also renders from `diagnostic` when `tally` is
   missing so a stale API process still updates the panel.
2. **The panel is read-only.** It does not choose the next step, jump books,
   or collect feedback. Clicking the chip reuses the existing source-page
   overlay ([ADR-0036](0036-ui-source-page-images.md)–[0038](0038-paragraph-highlight.md)).
3. **The API adds a computed `tally` object** on `POST /v1/diagnose` and the
   stream `done` event. The stored board schema is unchanged. Needle-only
   `test #N` rows display as `See TEST #N` and drop when a richer line already
   names that TEST.
4. **Clear the panel** on New chat and HTTP 410. Do not persist it.
5. **No per-check citation id** in this slice. Unused table causes are not
   invented when `next_check` is empty — show “Waiting” or omit Next.

## Consequences

- The operator can see the path without rereading the transcript.
- Measure with unit tests on the tally formatter. No retrieval fixture.
- A later slice may attach `evidence_index` per cleared check if live use
  shows the session chip is not enough.
