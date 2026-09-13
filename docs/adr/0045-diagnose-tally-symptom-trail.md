# ADR-0045: Session tally keeps each symptom and groups its checks

## Status

Accepted. Extends [ADR-0044](0044-diagnose-session-tally.md). Does not
replace the first `symptom_anchor` ([ADR-0031](0031-structured-diagnostic-state.md),
[ADR-0039](0039-diagnose-retrieve-labels.md)). Not R41. Not a flowchart.

## Context

A mid-session corrected problem (won’t open → opens but won’t close)
searches again ([ADR-0043](0043-session-evidence-reuse.md)). The tally
still showed only the first symptom, with every later check in one
**Checked** list. The operator could not see which checks belonged to
which problem.

Replacing `symptom_anchor` would break progress-follow-up search
fallback (ack / still unresolved / unclear map to the first problem).

## Options

| | A — Replace the Symptom line | B — Append spans; group checks | C — Interactive path editor |
| --- | --- | --- | --- |
| First problem visible | No | Yes | Yes |
| Checks stay with their problem | No | Yes | Yes |
| New protocol / R41 | No | No | Yes |
| Choice | Rejected | **Accepted** | Rejected |

## Decision

1. **`symptom_anchor` stays the first problem.** Classify `new_symptom`
   or `mid_cycle_stop` appends a span on the board (`symptom_path`).
   The span freezes the then-current `ruled_out` onto the previous
   problem. Later cleared checks belong to the new span.
2. **Computed `tally.segments`** is `[{symptom, cleared}, …]`. The
   existing `tally.symptom` / `tally.cleared` fields remain the first
   problem and the flattened list (compat). `/ui` renders each span,
   then one **Now asking** for the current pack.
3. **Read-only.** The panel still does not choose the next step, jump
   books, or collect feedback. Sessions stay in-memory
   ([ADR-0021](0021-api-hardening-embedder-sessions.md)).

## Consequences

- The trail matches the chat: unlock checks under the first complaint,
  lock checks under the corrected one.
- Measure with board/tally unit tests. No retrieval fixture.
- A missing classify label does not invent a span (no new slang regex).
