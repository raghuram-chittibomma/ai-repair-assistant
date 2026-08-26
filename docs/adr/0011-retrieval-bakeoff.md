# ADR-0011: Retrieval bake-off — keep ADR-0010 interim as production default

## Status

Accepted (does **not** supersede [ADR-0010](0010-retrieval-applicability.md); confirms it)

Amended by [ADR-0020](0020-hybrid-retrieval-retest.md): the decision stands, but
the hard-pass numbers below no longer reproduce against the current corpus, and
decision 2's stated reason ("hybrid diluted the ACU LED bulletin hit") is
withdrawn. Hybrid is rejected on precision and operational cost.

## Context

Charter deviation [D4](../CHARTER.md#deviations-from-this-charter) required comparing
lexical, vector, hybrid, and related approaches before locking retrieval.
Fixtures: `evals/retrieval/fixtures.yaml`. Scorecard:
`evals/retrieval/results/scorecard.md`.

Strategies scored (hard fixtures: ACU LED / door-lock wrong platform / F5E2
category / F6E1):

| Strategy | Hard pass |
| --- | --- |
| `vector_raw` | 3/4 |
| `vector_apply` | 3/4 |
| `vector_apply_boost` (ADR-0010) | **4/4** (after F5E2 KB fix) |
| `lexical_apply` | 2/4 |
| `hybrid_rrf_apply` | 2/4 |

## Decision

1. **Keep `vector_apply_boost` (ADR-0010) as the default** for `repair-corpus search`.
2. **Do not adopt pure lexical or RRF-hybrid yet** — lexical returned empty or
   weak sets on several fixtures; hybrid diluted the ACU LED bulletin hit.
3. **F5E2 KB gap (closed):** MindTouch pages title codes as `F5 E2` and nav chrome
   lists sibling codes. Fix: spaced-code recall, slug/lead extraction for MHTML,
   and knowledge-article ranking boosts. Re-run scorecard after corpus changes.
4. Re-run `repair-corpus bench-retrieve --write` when corpus or chunking changes.

## Consequences

- D4 moves from “experiments pending” to “experiments recorded; interim confirmed.”
- A future ADR may supersede 0010/0011 if KB retrieval or hybrid/rerank closes
  the F5E2 gap without regressing hard fixtures.
