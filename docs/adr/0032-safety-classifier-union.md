# ADR-0032: Regex ∪ optional LLM safety classifier

## Status

Accepted — review R3. Resolves the CI-independence tension with R26.

## Context

[ADR-0014](0014-safety-policy.md) made regex the pre-LLM authority so the LLM
is not the sole judge of repair risk. Review R3: regex alone has no paraphrase
robustness. The prescribed fix is regex **∪** a cheap classifier, taking the
maximum severity.

`bench-safety` is the only eval that can be a required CI check — it needs
neither OpenAI nor Postgres (R26). An LLM-only safety path would destroy that
gate.

R4's adversarial set already measures regex recall (~19% unsafe-recall, 0%
false-escalation). This ADR must not retune `policy.py` to chase that set.

## Options

| | A — Regex only | B — LLM only | C — Union, regex CI-gateable |
| --- | --- | --- | --- |
| Paraphrase recall | Weak | Better | Better |
| Jailbreak of classifier | N/A | Exposed | Regex still blocks literals |
| CI without OpenAI | Yes | No | Yes (`assess_request`) |
| Choice | Status quo (R3) | Rejected (R26) | **This ADR** |

## Decision

1. **`assess_request` stays regex-only.** `bench-safety` and the YAML pytest
   suite call it and remain the CI gate. `policy.py` is not retuned here.
2. **Runtime ask/diagnose** (when an OpenAI key is present and no test LLM is
   injected) call `assess_layered`: regex first, then a structured classifier
   **only if regex is not already `block`**. Merge takes the **maximum**
   severity. The classifier cannot lower a regex hit.
3. **Classifier failure is ignored.** Timeouts and parse errors keep the regex
   result so availability does not depend on the extra call.
4. **Union recall** on R4's set is a manual `bench-safety --classifier` (needs
   a key). Not a CI gate. Unit tests cover merge and a FakeClassifier on
   paraphrases the regex misses.
5. **Post-LLM `gate_answer` stays deterministic.** This slice is the pre-LLM
   request classifier only.

**Charter:** defence in depth; LLM is not the sole authority. No deviation.

## Consequences

- Each allow/warn/escalate ask or diagnose turn may add one small completion
  before retrieval when a key is set.
- CI safety recall stays the regex number. Product recall is the union, measured
  by hand.
- A classifier jailbreak still faces the regex arm and the post-LLM gate.
