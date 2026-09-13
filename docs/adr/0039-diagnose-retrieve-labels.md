# ADR-0039: Diagnose retrieve-time labels

## Status

Accepted. Implements the closed-set retrieve step named in
[ADR-0034](0034-diagnose-nlu-split.md). Progress follow-ups reuse the
session pack instead of searching again
([ADR-0043](0043-session-evidence-reuse.md)). Does not supersede
[ADR-0031](0031-structured-diagnostic-state.md) (no second board planner).
Does not open unconstrained query rewrite or ranking R11 / R20 / R22.

## Context

Turn 1 of diagnose is a symptom. Later turns are results (“looks good”,
“checked but still facing the issue”). Search was built from those user
strings (`_retrieval_query`). The generate call already saw the session
board, but only **after** retrieval. That hop cited the same door-lock
cause from another publication (service manual p.34 → tech sheet p.10).

[ADR-0034](0034-diagnose-nlu-split.md) accepted closed-set labels then OEM
family search, and forbade free paraphrase. The owner asked for that slice
with fixtures.

## Decision

1. **Turn 1:** no extra call. Query is the symptom (codes + existing expand).
2. **Turn 2+:** one classify completion. Input is the windowed transcript plus
   the formatted board. Output is one label — never a search string.
3. **Labels:** `ack` | `still_unresolved` | `mid_cycle_stop` | `new_symptom` |
   `unclear`.
4. **Rules map label → query** (OEM tokens only: symptom anchor, user-typed
   codes, `query_expand.yaml`):
   - `ack` / `still_unresolved` / `unclear` → symptom anchor + codes
   - `mid_cycle_stop` → latest utterance
   - `new_symptom` → latest + codes for this search; `symptom_anchor` stays
     server-owned ([ADR-0031](0031-structured-diagnostic-state.md))
5. **Diagnose-only stickiness** after `search()`, not inside the ask ranker:
   prefer the last turn’s cited `doc_id`; demote other-pub hits whose body
   overlaps `ruled_out` / prior `next_check`.
6. **Fallback:** no API key, timeout, or invalid JSON → today’s regex
   `_retrieval_query` / `acks.py`. Do not grow that regex as the product
   strategy.
7. **Ask mode unchanged.** `vector_apply_boost` unchanged.

## Consequences

- Subsequent diagnose turns can stay on the current guide after a result.
- Extra OpenAI call on turn 2+ when a key is present (LAN + paid exception).
- CI uses a fake classifier. Live `bench-qa` of
  `f5e2-door-lock-still-unresolved` is manual/scheduled.
- Free query rewrite remains rejected.
