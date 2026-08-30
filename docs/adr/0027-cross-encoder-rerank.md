# ADR-0027: Cross-encoder rerank is a bake-off strategy, not production

## Status

Rejected — measured on the 18-fixture decision set (2026-08-30).
`BAAI/bge-reranker-base` loses to `vector_apply_boost` on hard pass, MRR,
nDCG@K, and latency. Review R14 / slice 5 is closed for this model.

## Context

[ADR-0020](0020-hybrid-retrieval-retest.md) kept `vector_apply_boost` because
hand-written boosts move **8/14 → 14/14** and MRR **0.45 → 0.83**. Those
boosts are the retrieval system (review R12). A cross-encoder is the
principled replacement: score `(query, chunk)` pairs after applicability, and
delete the corpus-specific literals (R13 / R21) if it wins.

The charter listed reranking under evidence-driven architecture. It was never
measured. `bge-reranker-v2-m3` is MIT, offline, and CPU-runnable (~570 MB) but
contends with the BGE embedder on the same workstation. A same-family
`bge-reranker-base` CrossEncoder was the first bake so the experiment could
run without a second 570 MB download.

## Options

| | A — Do not measure | B — Bake-off only | C — Ship as default now |
| --- | --- | --- | --- |
| Cost | Zero | First-run model download + per-query CPU | Same, plus live latency |
| Evidence | None | MRR / nDCG / latency vs `vector_apply_boost` | Would adopt the boost stack's rival untested |
| Choice | Rejected | **This ADR** | Rejected |

## Decision

1. Bake-off strategy `vector_apply_rerank` stays in `bench-retrieve` as a
   control: vector overfetch + `code_fetch` + applicability + cross-encoder,
   **no** authority boosts.
2. Default model remains `BAAI/bge-reranker-base`. `REPAIR_RERANK_MODEL` can
   still select another CrossEncoder for a later bake.
3. Do **not** call the reranker from `search()` / ask / diagnose.
4. Do **not** adopt. Hard-pass regression and worse MRR/nDCG/latency all
   trigger reject (this record's own rule).
5. Do **not** delete R13 / R21 literals on this evidence.

**Charter:** no deviation. Local OSS weights; OpenAI unused.

## Measurement (2026-08-30)

`evals/retrieval/results/scorecard.md` after `bench-retrieve --write`.
Model: `BAAI/bge-reranker-base`. 18 fixtures, 15 labeled, 14 hard.

| Strategy | Hard | mean MRR | mean nDCG@K | mean Precision@K | Latency mean / p95 |
| --- | ---: | ---: | ---: | ---: | --- |
| `vector_apply_boost` | **14/14** | **0.83** | **0.87** | 0.48 | **118 / 182 ms** |
| `vector_apply` (no boosts) | 8/14 | 0.45 | 0.50 | 0.30 | 115 / 149 ms |
| `vector_apply_rerank` | **10/14** | **0.57** | **0.62** | 0.37 | **35929 / 241819 ms** |

Rerank recovered three `vector_apply` misses (`tech-sheet-page1-by-pub`,
`manual-rev-b-acu-led`, `f5e2-tech-sheet-not-kb`) and dropped one apply-pass
(`part-number-door-lock` — parts list left the top-K). Remaining hard fails
match the boost-dependent cases: ACU LED bulletin (`acu-led-step-10`),
shipping-bolt vocabulary (`transport-bolt-vocabulary`), plus the synth
supersession `must_not_cite`.

p95 includes first-load of the CrossEncoder. Mean ~36 s is still ~300× the
baseline. A larger model (`bge-reranker-v2-m3`) is a different experiment,
not implied by this reject.

## Consequences

- Production path and `vector_apply_boost` remain the baseline.
- R13 / R21 literals stay until a later measured replacement wins.
- `vector_apply_rerank` remains a bake-off row so the reject stays
  re-runnable. It is not on the live path.
