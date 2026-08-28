# 06 — Safety

Deterministic policy — not LLM-only. Pre-LLM assessment can block before
retrieval; warn/escalate inject prompt framing; post-LLM gate strips unsafe
procedures from generated text.

## End-to-end gates

```mermaid
flowchart TD
  q[Question_plus_audience]
  assess[assess_request]
  blocked[Safe_refusal]
  retrieve[Retrieve]
  inject[Warn_or_escalate_prompt]
  ownerEv[apply_owner_evidence_policy]
  llm[LLM_generate]
  gate[gate_answer]
  cite[Citation_grounding_check]
  out[Answer_or_escalation]

  q --> assess
  assess -->|block| blocked
  assess -->|allow| retrieve
  assess -->|warn_or_escalate| inject
  inject --> retrieve
  retrieve --> ownerEv
  ownerEv --> llm
  llm --> gate
  gate --> cite
  cite --> out
```

- **Actions:** `allow` / `warn` / `escalate` / `block` ([ADR-0014](../adr/0014-safety-policy.md)).
- **Pre-LLM:** `block` skips the LLM with a fixed message; `warn` / `escalate` inject directives into the system prompt.
- **Post-LLM:** `gate_answer` strips bypass language and owner TEST # / live-voltage walkthroughs even if the model oversteps.
- **UX:** Sticky banner on block / escalate in `/ui`.

## Audience rule sets

```mermaid
flowchart LR
  q[Question]
  aud{Audience}
  ownerRules[Owner_rule_list]
  techRules[Technician_rule_list]
  pick[Highest_severity_match]
  action[allow_warn_escalate_block]

  q --> aud
  aud -->|owner| ownerRules
  aud -->|technician| techRules
  ownerRules --> pick
  techRules --> pick
  pick --> action
```

| Audience | Typical outcomes |
| --- | --- |
| Owner | Escalate live voltage / panel / board work; block bypass / defeat-safety; prefer owner literature when present |
| Technician | Warn on live procedures; still **block** interlock bypass; broader TEST # access |

Rules are regex lists in `safety/policy.py` — maintainable fixtures, not an LLM judge. Graded by `repair-corpus bench-safety` without OpenAI or Postgres.

## Post-LLM gate (owner hard stops)

```mermaid
flowchart TD
  raw[Model_text]
  bypass[Bypass_or_jumper_scan]
  proc[Unsafe_procedure_scan]
  test[Owner_TEST_voltage_scan]
  rewrite[Replace_or_escalate_text]
  pass[Pass_through]

  raw --> bypass
  bypass -->|hit| rewrite
  bypass --> proc
  proc -->|hit| rewrite
  proc --> test
  test -->|hit| rewrite
  test -->|clean| pass
```

- **G1 — owner vs tech segregation:** `apply_owner_evidence_policy` + post-gate block of TEST # / voltage walkthroughs for owners.
- **G2 — expanded hazards:** Defeat safety, capacitor, tip-over, water-line mod, etc. (see `evals/safety/fixtures.yaml`).
- **G3 — citation grounding:** Procedural checklists without `[n]` citations abstain via `needs_grounding_citation`.

**Modules:** `safety/policy.py`, `safety/gate.py`, `safety/models.py` · bench: `evals/safety/fixtures.yaml`
