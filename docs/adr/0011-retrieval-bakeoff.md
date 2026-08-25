# ADR-0011: Retrieval bake-off — keep ADR-0010 interim as production default

## Status

Accepted (does **not** supersede [ADR-0010](0010-retrieval-applicability.md); confirms it)

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
| `vector_apply_boost` (ADR-0010) | **3/4** |
| `lexical_apply` | 2/4 |
| `hybrid_rrf_apply` | 2/4 |

## Decision

1. **Keep `vector_apply_boost` (ADR-0010) as the default** for `repair-corpus search`.
2. **Do not adopt pure lexical or RRF-hybrid yet** — lexical returned empty or
   weak sets on several fixtures; hybrid diluted the ACU LED bulletin hit.
3. **Known gap:** all strategies fail `f5e2-front-load-not-top-load` because the
   MindTouch KB chunks are not retrieved into top-K (tech sheets dominate). Treat
   as a follow-up (chunking/ingest of KB articles + stronger exact-code lexical),
   not a reason to switch strategies today.
4. Re-run `repair-corpus bench-retrieve --write` when corpus or chunking changes.

## Consequences

- D4 moves from “experiments pending” to “experiments recorded; interim confirmed.”
- A future ADR may supersede 0010/0011 if KB retrieval or hybrid/rerank closes
  the F5E2 gap without regressing hard fixtures.
