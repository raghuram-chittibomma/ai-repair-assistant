# ADR-0041: Unlock retrieve is stuck-closed OEM, not F5E2

## Status

Accepted. Follows [ADR-0040](0040-door-polarity-grammar.md) (polarity
label). Does not change `vector_apply_boost`, ranking R11 / R20 / R22,
or diagnose retrieve labels ([ADR-0039](0039-diagnose-retrieve-labels.md)).

## Context

ADR-0040 correctly labels `door doesn't open` as unlock. Live diagnose
still cited TEST #4 / F5E2 p.32. Two injectors searched the lock-system
chapter:

- Unlock `add_to_search` included `lock failure` and `F5E2` (TEST #4
  tokens in W11169652, not the owner “Door will not unlock” row).
- `suggest_plan_codes` appended F5E2 whenever polarity was unlock and
  the user had not typed it. `plan.codes` feeds `code_fetch`. Diagnose
  turn 1 uses the same `plan_for_query`.

`_UNLOCK_EVIDENCE` then treated `f5e2` / `lock failure` as unlock hits,
so `check_evidence_fit` accepted the pack. Provenance (“If the display
shows F5E2”) cannot save an answer once TEST #4 is in the numbered
blocks.

## Options

| | A — Keep F5E2 fetch, tighten generate | B — Mention F5E2 in the prompt, still fetch | C — Unlock family is stuck-closed OEM only |
| --- | --- | --- | --- |
| Stops TEST #4 on a no-code first line | No | No | Yes |
| Extra LLM / ranking constants | Maybe | No | No |
| F5E2 still retrieved when the user types it | Yes | Yes | Yes (`user_codes`) |
| Choice | Rejected | Rejected | **Accepted** |

## Decision

1. **Unlock `add_to_search` is stuck-closed OEM only:** `door will not
   unlock`, `door will not open`, `Door locks when cycle has started`.
   Do not put fault codes or TEST #4 glosses (`F5E2`, `lock failure`)
   in that list.
2. **`suggest_plan_codes` does not inject F5E2** from polarity. A code
   the user typed stays in `user_codes` and still hits `code_fetch`.
3. **`_UNLOCK_EVIDENCE` is owner unlock cues only** (`will not unlock`,
   Add Garment, cycle-started lock, START/PAUSE). F5E2 / lock failure
   are not polarity evidence.
4. Ask and diagnose turn 1 share this plan. Technician depth still
   applies when the user types F5E2 or a depth question.

## Consequences

- `door doesn't open` / `door got locked` retrieve unlock literature,
  not TEST #4, unless the user reported F5E2.
- Smoke fixtures `door-got-locked-unlock` and `door-doesnt-open-unlock`
  fail on TEST #4 and do not treat bare `open` as a pass.

**Charter:** evidence-driven architecture; no stack deviation. OpenAI
stays LLM-only. No new required cloud dependency.
