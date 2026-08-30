# ADR-0020: Hybrid retrieval re-tested on rare literals — keep `vector_apply_boost`

## Status

Accepted (confirms [ADR-0010](0010-retrieval-applicability.md) and
[ADR-0011](0011-retrieval-bakeoff.md); does not supersede either)

**Amended 2026-08-26:** fixture gate and ranking evolved after a product-class
coverage review. The decision is unchanged; measured numbers below the
[Amendment](#amendment-2026-08-26--product-class-gate) heading supersede the
9-hard-fixture table in the original body. Original rare-literal findings are
retained as history.

## Context

[ADR-0011](0011-retrieval-bakeoff.md) rejected lexical and RRF-hybrid retrieval
on a six-fixture bake-off. Two objections to that record were raised and are
both fair:

1. **The evidence was thin.** Four hard fixtures cannot distinguish "equivalent"
   from "not enough signal to distinguish". On a re-run against the current
   corpus, `hybrid_rrf_apply` no longer scored 2/4 as recorded in ADR-0011 — it
   tied `vector_apply_boost` at 4/4 with identical mean Precision@K (0.49).
   The recorded reason for rejecting it had stopped being true.
2. **The hybrid that was tested was the wrong one.** `_rrf` overwrites `score`
   with reciprocal ranks of ~1/60. The boosts in `filter_and_rank` run
   0.02–0.35, an order of magnitude larger, so under `hybrid_rrf_apply` the
   deterministic boosts are effectively the entire ranking function and the
   fusion order survives only as noise. A magnitude-preserving union of the two
   candidate pools had never been benchmarked.

There was also a standing structural argument for a lexical arm: `search()` had
accumulated four hand-rolled exact-match retrievers (`code_fetch`,
`connector_fetch`, `manual_rev_fetch`, `reference_fetch`), each added after a
specific rare-token failure. That is hybrid retrieval built one regex at a time.

### Fixture set expanded (original, rare-literal wave)

`evals/retrieval/fixtures.yaml` grew from 6 fixtures (4 hard) to 12 (9 hard).
The six additions target rare-literal recall, with ground truth verified by
probing the ingested `chunks` table for each literal rather than inferred from
the manifest. The set is deliberately mixed: part numbers and connector IDs
should favour a lexical arm, while `transport-bolt-vocabulary` should favour the
dense arm, because the installation instructions say "transport bolts" and never
"shipping bolts". A strategy that wins the literal fixtures by losing that one
has not improved.

### Postgres full-text search cannot rank rare literals

Measured on the query `Is part number W10804741 the door lock for my washer?`:

- `plainto_tsquery` ANDs every lexeme —
  `'part' & 'number' & 'w10804741' & 'door' & 'lock' & 'washer'` — which matches
  **zero** chunks, because the target is a terse mangled parts-table row
  (`15 W10804741 Lock,Door`). This, not stemming, is why `lexical_apply`
  returned empty sets on five fixtures.
- Relaxing to OR semantics fixes the empty result but not the ranking: the
  target chunk falls outside the top 10 while `kb-error-codes-front-load` scores
  6.2, because `ts_rank_cd` has **no IDF term**. Rarity, the only thing that
  makes `W10804741` decisive, is not expressible.
- The literal alone retrieves exactly one chunk — the right one — at rank 0.1.

Two new strategies were therefore benchmarked instead of one:

- `union_lexical_apply` — vector ∪ OR-semantics full-text, affine-mapped onto
  the observed vector score band so magnitudes survive, then apply + boosts.
  This is textbook hybrid, done without RRF's flattening.
- `union_literal_apply` — vector ∪ rare-literal exact match, same magnitude
  handling. Generalises the four side doors: mixed alphanumeric query tokens are
  matched exactly, and any literal appearing in more than 40 chunks is skipped,
  which supplies the IDF cutoff Postgres will not.

## Measured result (original, 9 hard)

Scorecard at that time: 12 fixtures, 9 hard, K=8, overfetch 40.

| Strategy | Hard pass | Hit@K | mean Precision@K |
| --- | --- | ---: | ---: |
| `vector_apply_boost` (default) | **9/9** | 1.00 | 0.45 |
| `hybrid_rrf_apply` | **9/9** | 1.00 | 0.46 |
| `union_literal_apply` | **9/9** | 1.00 | 0.46 |
| `union_lexical_apply` | **9/9** | 1.00 | **0.36** |
| `vector_apply` | 7/9 | 0.80 | 0.45 |
| `vector_raw` | 6/9 | 0.80 | 0.36 |
| `lexical_apply` | 5/9 | 0.50 | 0.67 (n=5) |

Four strategies saturated the gate at 9/9. `lexical_apply`'s precision was a
selection effect — averaged over only the fixtures where it returned anything.

Three findings from that wave:

1. **The boosts are load-bearing.** `vector_apply` → `vector_apply_boost`
   moved 7/9 → 9/9. `test-10a-measured-values` and `transport-bolt-vocabulary`
   failed without boosts and passed with them.
2. **A full-text arm actively hurts.** `union_lexical_apply` cost ~0.09 mean
   precision for zero recall gain.
3. **The dense arm already recalls rare literals.** `vector_apply` alone passed
   both part-number fixtures — no recall gap for a lexical arm to close.

## Decision

1. **Keep `vector_apply_boost` as the production default.**
2. **Do not adopt a Postgres full-text arm.** Measurably worse precision, no
   recall gain; root cause (no IDF in `ts_rank_cd`) is not tunable. A
   BM25-capable index would be a separate ADR.
3. **Keep `union_literal_apply` in the bake-off, unadopted.** Precision-neutral
   today; retained as the candidate if corpus growth dilutes dense rare-token
   recall.
4. **Correct the ADR-0011 record.** Hybrid is rejected on precision and
   operational cost, not on the obsolete “diluted ACU LED” claim.
5. Re-run `repair-corpus bench-retrieve --write` when the corpus, chunker,
   embedding model, or retrieval gate changes.

## Amendment 2026-08-26 — product-class gate

A coverage review against typical OEM service-literature types (not limited to
the held Whirlpool corpus) found the 9-hard set overloaded on exact identifiers
and missing near-dup sheets, revision letter, bibliographic pub lookup,
engineering digit, multi-brand platform, and new-pub supersession.

### Gate changes

- Hard fixtures: **9 → 14** (soft demotions of near-duplicate exact-id cases).
- Ready-now additions on held docs: `tech-sheet-page1-by-pub`,
  `manual-rev-b-acu-led`, `f5e2-tech-sheet-not-kb`,
  `publication-what-is-w11375982`, `adjacent-model-parts-exclude`,
  `maytag-mhw-platform-manual`.
- **Synthetic eval pack** under `evals/retrieval/synthetic/` for blocked
  supersession (`SYNTH-UC-100` / `SYNTH-UC-200`). Rules: `synth-` / `SYNTH-`
  prefixes only; never under `corpus/`; upserted only by `bench-retrieve`;
  production `search()` strips them.
- Ranking additions that closed the two universal hard fails on the expanded
  gate: named-publication prefer/hard-filter (part-number `W########` excluded);
  technician-depth prefer tech sheet/manual over consumer KB; `superseded_by`
  demotion for the synthetic pair.

### Latest measured result

Scorecard: `evals/retrieval/results/scorecard.md` (18 fixtures, **14 hard**,
K=8, overfetch 40; includes synthetic).

| Strategy | Hard pass | Hit@K | mean Precision@K |
| --- | --- | ---: | ---: |
| `vector_apply_boost` (default) | **14/14** | 1.00 | 0.45 |
| `hybrid_rrf_apply` | **14/14** | 1.00 | 0.46 |
| `union_literal_apply` | **14/14** | 1.00 | 0.45 |
| `union_lexical_apply` | **14/14** | 1.00 | **0.40** |
| `vector_apply` | 8/14 | 0.60 | 0.29 |
| `vector_raw` | 6/14 | 0.60 | 0.22 |
| `lexical_apply` | 7/14 | 0.40 | 0.60 (n=6) |

### Amendment findings

1. **Decision unchanged.** Expanding the gate did not create a recall case that
   only hybrid wins. Leaders again tie on pass/fail; Precision@K still
   disfavours `union_lexical_apply` (0.40 vs 0.45).
2. **Boosts are more load-bearing, not less.** `vector_apply` →
   `vector_apply_boost` is now 8/14 → 14/14 (was 7/9 → 9/9). New misses without
   boosts include named-pub / revision / tech-depth / supersession cases.
3. **Synthetics are a valid IR stand-in when OEM bytes are missing**, provided
   they stay namespaced and out of production retrieval. They do not replace
   acquiring `W11355369` for the real supersession Q&A scenario.
4. **Pass/fail is saturated again among leaders.** Further discrimination needs
   either fixtures the default still fails, Precision@K as a secondary metric,
   or grading production `search()` (side doors) rather than bake-off cores only.

### Decision restated

Items 1–5 in [Decision](#decision) stand. Additionally:

6. **Eval synthetics are allowed** under `evals/retrieval/synthetic/` with the
   isolation rules above; they are not corpus literature.
7. **Named-publication and technician-depth ranking** are part of the ADR-0010
   boost surface, not a strategy change.

## Amendment 2026-08-30 — rank-sensitive metrics; production path

`bench-retrieve` now reports MRR, nDCG@K, and `run_strategy` latency (review
R29). The owner waived a separate held-out test set; these numbers are on the
current 18 fixtures (15 labeled).

| Strategy | Hard | mean MRR | mean nDCG@K | mean Precision@K | Latency mean / p95 |
| --- | ---: | ---: | ---: | ---: | --- |
| `vector_apply_boost` | 14/14 | 0.83 | 0.87 | 0.48 | 119 / 186 ms |
| `union_literal_apply` | 14/14 | 0.83 | 0.87 | 0.48 | 172 / 298 ms |
| `hybrid_rrf_apply` | 14/14 | 0.77 | 0.83 | 0.49 | 413 / 456 ms |
| `union_lexical_apply` | 14/14 | 0.65 | 0.74 | 0.39 | 628 / 748 ms |
| `production_search` | 10/14 | 0.58 | 0.60 | 0.44 | 209 / 1241 ms |
| `vector_apply` | 8/14 | 0.45 | 0.50 | 0.30 | 109 / 139 ms |

### Amendment findings

1. **Decision unchanged.** `vector_apply_boost` remains the bake-off baseline.
   `union_literal_apply` ties it on MRR/nDCG and is slower. Hybrid still loses
   on rank and latency.
2. **Pass/fail is still saturated** among those three 14/14 strategies. Rank
   metrics are the discriminator, not another hard-fixture count.
3. **`production_search` (ask/diagnose) was 10/14** because
   `prefer_owner_literature` defaulted the planner audience to owner and then
   dropped tech sheets and parts lists whenever any owner-facing hit existed.
   Identifier and technician-depth queries now skip that hard filter.

### Decision restated again

Items 1–7 stand. Additionally:

8. **Do not switch production ranking to hybrid or union-lexical** on this
   evidence. Keep `vector_apply_boost` as the measured core.
9. **Owner-literature restriction does not apply** to identifier /
   technician-depth / bibliographic questions.

## Consequences

- Release gate: **14 hard fixtures** spanning applicability, precedence,
  rare literals, term mismatch, near-dup identity, revision, bibliographic
  lookup, multi-brand, and synthetic supersession.
- Full-text hybrid remains a bake-off control, not production.
- `production_search` grades the live `search()` path (side doors + planner).
  Compare it to `vector_apply_boost` on MRR/nDCG, not only hard pass/fail.
- Chunking (ADR-0007) was not reopened; residual product-class gaps that look
  boundary-shaped should get a targeted micro-bake, not a full D4 redo.
