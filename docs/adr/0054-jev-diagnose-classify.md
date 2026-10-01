# ADR-0054: Jev for diagnose turn classification

- **Status:** Accepted
- **Date:** 2026-10-01
- **Measured:** `evals/diagnose/results/scorecard.md` — Jev **18/20 (90%)** vs
  OpenAI **14/20 (70%)** vs regex **6/20 (30%)**; mean latency ~215 ms vs
  ~1436 ms. Cost estimate (official `$0.042/M` input) lower for Jev on this
  pack (~$0.0004 vs ~$0.0009 OpenAI list).

## Context

Turn 2+ diagnose classify returns one closed-set label
([ADR-0039](0039-diagnose-retrieve-labels.md)): `ack` |
`still_unresolved` | `mid_cycle_stop` | `new_symptom` | `unclear`. Rules
build the search query; the model must not write query text
([ADR-0034](0034-diagnose-nlu-split.md)).

That classify call used OpenAI structured JSON when `OPENAI_API_KEY` is set
(`live_intent_complete`). TypeSafe AI’s **Jev** System One API returns typed
`choice` / `score` / `noul` decisions without generative prose — a natural
fit for the closed-set label only. The owner accepted a second hosted API for
this slice (cost OK).

## Decision

1. **Scope:** diagnose retrieve-time classify only. Generate, safety union,
   semantic propose/assist, and ranking stay unchanged.
2. **API:** `POST https://api.typesafe.ai/v1/systemone` (override with
   `JEV_DECIDE_URL`; the `jevtypesafeai.com` mirror expects `jv_live_` keys)
   with one `choice` question whose criteria keys are the five ADR-0039
   labels. `state` is board text + transcript window (same content as today’s
   classify user prompt). Pin `JEV_MODEL` (`jev-1.13.0` on the Accept
   scorecard).
3. **Env:** `JEV_API_KEY` (`apikey_…` or `jv_live_…`). Optional `JEV_MODEL`,
   `JEV_MIN_CONFIDENCE` (below threshold → treat as classify miss),
   `JEV_DECIDE_URL`, `JEV_TIMEOUT_SECONDS`.
4. **Preference:** Jev if key set → else OpenAI if key set → else regex /
   `acks.py` fallback (unchanged). API failure, invalid choice, or low
   confidence → same fallback as a classify timeout today.
5. **Charter:** bounded second hosted API for classify only (deviation
   **D10**; sibling to D1 LLM exception; does not weaken D8 LAN product
   surface). OpenAI remains required for answer generation.
6. **Eval:** `bench-diagnose-intent` on
   `evals/diagnose/intent-fixtures.yaml`. Re-measure when changing label
   criteria or the pinned model.
7. **Non-goals:** free query rewrite; growing synonym regex as strategy;
   R11 / R20 / R22; safety classifier swap (separate ADR if reopened).

## Consequences

- Optional cloud dependency and key for turn 2+ diagnose classify.
- CI stays offline (fake / mocked classifier). Live bake-off is manual.
- `_session_classify_turn` prefers Jev when `JEV_API_KEY` is set.

## Alternatives considered

| | Keep OpenAI classify | Jev `choice` | Local small classifier |
| --- | --- | --- | --- |
| Typed labels | Via JSON schema | Native | Needs train/data |
| Latency / cost | Full LLM call | Faster on measured pack | No cloud |
| Charter fit | Existing D1 | New bounded hosted exception (D10) | Best for D8 |
| Measured accuracy | 70% | **90% (chosen)** | Deferred — no labelled train set |
