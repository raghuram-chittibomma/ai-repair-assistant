# ADR-0052: Pre-LLM weak-evidence abstain gate

## Status

Accepted.

## Context

`search()` returns a fixed top‑K (default 8) with **no cosine floor**. After
applicability, the pack can be the best of a weak set: every hit applies to the
model but none are on-topic. Empty packs already abstain
(`ABSTAIN_NO_EVIDENCE`). Weak-but-nonempty packs still call the answer LLM, which
can produce a cited answer from off-topic OEM text.

This is **not** frozen ranking work R22 (diagnose anti-abstain coercion on
progress turns). R22 stays out of scope.

## Measured approach (threshold)

Live/Langfuse ask packs that look useful often show top hit `score` in the
~0.75–0.94 range after boosts; off-topic top‑K can sit much lower. Exact arms
(`code_fetch` / `connector_fetch`) stamp `score = 1.0` (neighbors `0.95`);
named publication / revision arms stamp `0.85` / `0.88`. A single global floor
on `final_score` would either kill those arms or fail to catch weak vector-only
packs.

Until distributions are calibrated on pass fixtures vs a negative probe set:

- Gate is **off** unless `REPAIR_WEAK_EVIDENCE_MIN_SCORE` is set to a positive
  float (suggested starting calibration band: **0.50–0.55**).
- Target: near-zero new abstains on the retrieval decision set; high abstain on
  nonsense / off-corpus probes.

## Decision

1. **Deterministic pre-LLM gate** after search / hit selection, before
   `format_evidence` and the answer LLM.
2. **Weak pack** when **both** hold:
   - No high-precision arm contribution in the selected hits (exact code /
     connector overlap with the query, or named publication / revision match).
   - Among selected hits, `max(score) < T` where `T` is
     `REPAIR_WEAK_EVIDENCE_MIN_SCORE`.
3. **Exact-arm sentinel:** `score >= 0.999` always counts as precision (covers
   stamped `1.0` code/connector seeds even without re-parsing the query).
4. **Scope:** ask, and diagnose turns that **search**. Skip when diagnose
   **reuses** the session evidence pack ([ADR-0043](0043-session-evidence-reuse.md)).
5. **User-facing code:** `ABSTAIN_WEAK_EVIDENCE` — short message that the
   documentation set has no sufficiently matching evidence. Same response shape
   as other abstains.
6. **Tracing:** Langfuse records `weak_evidence_gate`, `top_vector_score`, and
   `threshold` on the gate observation.

## Consequences

- CI and default LAN installs keep current behavior until `T` is set.
- Operators can tune `T` from traces without a code change.
- Does not change ranking strategy, R22 prompts, or PDF-attach fallbacks
  ([ADR-0051](0051-pdf-primary-semantic-evidence.md)).

## See also

[architecture/04](../architecture/04-retrieval.md) ·
[architecture/05](../architecture/05-runtime-ask-diagnose.md)
