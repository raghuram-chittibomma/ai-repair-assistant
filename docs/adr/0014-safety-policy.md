# ADR-0014: Deterministic repair safety policy and escalation

## Status

Accepted

## Context

Phases 5–6 ground answers and diagnostics in manufacturer evidence
([ADR-0012](0012-grounded-qa.md), [ADR-0013](0013-langgraph-diagnostic.md)).
The charter requires safety as a **product requirement**, not only a prompt
instruction: the LLM must not be the sole authority on repair risk (charter
Safety section; Phase 8).

## Decision

1. **Policy module** (`src/repair_assistant/safety/`): regex-based rules classify
   user requests into `allow`, `warn`, `escalate`, or `block` before generation.
2. **Audience tiers:** `owner` (default) vs `technician` (`--audience` on
   `ask` / `diagnose`). Owners are escalated for live voltage, panel removal,
   and control-board work; technicians receive warnings but not bypass help.
3. **Pre-LLM gate:** `block` skips the LLM entirely with a fixed message.
   `escalate` / `warn` inject safety directives into the system prompt.
4. **Post-LLM gate:** deterministic scan removes interlock-bypass language and
   replaces unsafe procedural steps for owner audiences even if the model
   oversteps.
5. **Bench:** `repair-corpus bench-safety` grades `evals/safety/fixtures.yaml`
   without OpenAI or Postgres — CI-safe regression for policy rules.
6. **Out of scope:** full LLM-judged safety eval harness (Phase 9); formal
   product UX for escalation (Phase 10).

**Charter alignment:** implements Phase 8 (README Phase 7). No new deviations.

## Consequences

- Safe answers may prepend escalation framing for owner voltage questions while
  still allowing diagnostic explanation when the model complies.
- Technician mode permits procedural citations but never bypass instructions.
- Policy rules are maintainable regex lists; corpus-specific hazards should be
  added as fixtures when discovered.
- Automated grading of “correct escalation wording” awaits the Phase 9 eval
  harness; deterministic action classification is enforced in CI today.
