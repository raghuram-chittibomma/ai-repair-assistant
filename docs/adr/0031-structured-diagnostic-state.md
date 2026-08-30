# ADR-0031: Diagnose carries an inspectable board, not only a transcript

## Status

Accepted — review R31.

## Context

[ADR-0013](0013-langgraph-diagnostic.md) stores `messages` plus this turn's
evidence and safety flags. "Which checks were cleared" is re-derived by the
model rereading the transcript. That is why `diagnose_system.txt` needs several
rules about not inventing ruled-out checks, and why trajectory evals can only
score prose.

Review R31: the charter asked for explicit workflow state (hypotheses,
observations, ruled-out, a step). Without it there is no repair summary, no
handoff, and no machine-checkable trajectory.

Durable session storage is [ADR-0025](0025-deferred-scope-multi-user-outcome-curation.md)
/ R32 — out of scope here.

## Options

| | A — Transcript only | B — Board on session state | C — Separate planner LLM |
| --- | --- | --- | --- |
| Inspectable | No | Yes | Yes |
| Extra call | No | No | Yes |
| CI | Prompt rules | Merge + optional `turn_grades` | Same as B plus cost |
| Choice | Rejected | **This ADR** | Rejected (R23 already chose one structured completion) |

## Decision

1. **`DiagnosticBoard`** lives on `DiagnosticGraphState` and survives in-memory
   turns: `step`, `phase`, `symptom_anchor`, `hypotheses`, `ruled_out`,
   `observations`, `next_check`.
2. **`step` and `symptom_anchor` are server-owned.** Step is the human-turn
   count. The anchor is the existing first-substantive-user-message heuristic
   and cannot be cleared by the model.
3. **The diagnose JSON schema** (not ask) adds a `diagnostic` object. The
   model proposes phase / hypotheses / ruled-out / observations / next check.
   A deterministic merge unions `ruled_out`, drops those items from
   `hypotheses`, appends unique observations, and keeps the latest
   `next_check`. User text is always recorded as an observation even when the
   model omits `diagnostic` (tests, prose fallback).
4. **The board is injected** into the diagnose user prompt as authoritative
   session state. The model must not invent ruled-out checks that are not on
   the board.
5. **The board is on** `TurnResult`, `/v1/diagnose`, and the stream `done`
   event. `turn_grades` may use `expect_phase`, `expect_ruled_out_any`, and
   `expect_hypotheses_any`. Those keys are optional; existing prose fixtures
   stay valid.
6. **No second LLM call.** No Postgres session row. No ranking change.

**Charter:** implements inspectable diagnostic state from Phase 7. No deviation.

## Consequences

- Trajectory fixtures can assert board fields without an OpenAI judge.
- A model that omits `diagnostic` still accumulates user observations and step.
- Repair-summary / technician handoff remain future product work on top of
  this board. R32 persistence is still deferred.
