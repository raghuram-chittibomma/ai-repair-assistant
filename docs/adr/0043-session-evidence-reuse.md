# ADR-0043: Session evidence is sticky on progress follow-ups

## Status

Accepted. Extends [ADR-0039](0039-diagnose-retrieve-labels.md) retrieve
timing. Does not change closed-set labels, `vector_apply_boost`, or
ranking R11 / R20 / R22. Sessions stay in-memory
([ADR-0021](0021-api-hardening-embedder-sessions.md)).

## Context

Diagnose generate already writes the next step from numbered evidence.
Every follow-up still called `search()`, so `[n]` could become a
different book after “checks passed” or “still facing the issue.”
`stick_diagnose_hits` then demoted a coalesced checklist that named
`See TEST #N`, which evicted the category the user was on.

That is retrieve amnesia, not a weak LLM. The system prompt forbids
using anything but this turn’s blocks, so a swapped pack cannot
continue last turn’s path. The failure is general (any Guide #1
category with a See TEST pointer), not one utterance.

Unconstrained query rewrite and a rule-only flowchart stay rejected
([ADR-0034](0034-diagnose-nlu-split.md)). A second planner LLM for the
board stays rejected ([ADR-0031](0031-structured-diagnostic-state.md)).

## Options

| | A — Re-search and demote TEST lines | B — Model writes the next query | C — Reuse the session pack on progress |
| --- | --- | --- | --- |
| Same `[n]` after “checks passed” | No | Maybe | Yes |
| Hallucinated search words | No | Yes (R18) | No |
| Extra ranking constant | Risk | No | No |
| Choice | Rejected | Rejected | **Accepted** |

## Decision

1. **Progress follow-ups reuse the last evidence pack** when one exists:
   `evidence_text`, citations, evidence blocks, and figure pages.
   Do not call `search()`. Applies to classify labels `ack` and
   `still_unresolved`, and to the `acks.py` fallback when classify is
   unavailable or `unclear`.
2. **Search again** on the first substantive turn, and when classify
   returns `new_symptom` or `mid_cycle_stop` (corrected problem).
3. **Generate stays claim-grounded** on the pack in hand
   ([ADR-0012](0012-grounded-qa.md), [ADR-0028](0028-structured-claim-evidence.md),
   [ADR-0029](0029-claim-groundedness.md)). Images stay orientation-only
   ([ADR-0035](0035-late-fusion-page-images.md)). If the pack has no
   unused cause or only a See TEST #N *name* without that TEST’s steps,
   cite the pointer or close — do not invent the procedure and do not
   search just to look helpful.
4. **Classify still returns a label only** ([ADR-0039](0039-diagnose-retrieve-labels.md)).
   The model does not write the search query.
5. **Not a ranking change.** Same-problem coalesce remains formatting
   ([ADR-0042](0042-guide1-anchor-and-checklist-coalesce.md)).

## Consequences

- “Checked / no issues” and “tried, still broken” keep the same
  literature so the generate LLM can advance or close on that path.
- Opening a TEST procedure that is not in the pack is a later retrieve
  (user asks, or a future closed-set `open_see_test` label).
- Measure with generic progress-follow-up unit tests plus existing
  mid-cycle and F5E2 fixtures. Live checklist scripts are examples,
  not the spec.
