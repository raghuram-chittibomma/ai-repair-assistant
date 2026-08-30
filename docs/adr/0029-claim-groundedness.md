# ADR-0029: Claim groundedness is measured, not only citation identity

## Status

Accepted — review R27. Depends on [ADR-0028](0028-structured-claim-evidence.md).

## Context

`grade_answer` checked **which** documents were cited. An invented procedure
with a valid `[n]` passed every deterministic rule. The LLM judge never saw
evidence blocks, so it could not score faithfulness either.

## Decision

1. **Deterministic check** over `(claim, evidence block)` pairs from ADR-0028.
   A claim is supported when it is a near-substring of the cited block or most
   of its content tokens appear there.
2. **Hard fail** only on zero token overlap (or an uncited procedural claim).
   Weak paraphrase overlap is counted, not a gate fail — that is the
   unsupported-claim **rate**, not a second 14/14.
3. **`bench-qa` scorecard** reports unsupported/checked per scenario and the
   mean rate.
4. **Judge** receives the evidence blocks. Calibration cases without evidence
   stay answer-only.

**Charter:** implements “citation correctness must itself be evaluated.”

## Consequences

- Live `bench-qa` will start showing a groundedness column; first numbers are
  the baseline, not a release gate.
- Paraphrases the lexical check misses still need `--judge` plus evidence.
