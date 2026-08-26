# ADR-0020: Hybrid retrieval re-tested on rare literals — keep `vector_apply_boost`

## Status

Accepted (confirms [ADR-0010](0010-retrieval-applicability.md) and
[ADR-0011](0011-retrieval-bakeoff.md); does not supersede either)

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

### Fixture set expanded

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

## Measured result

Scorecard: `evals/retrieval/results/scorecard.md` (12 fixtures, 9 hard, K=8,
overfetch 40).

| Strategy | Hard pass | Hit@K | mean Precision@K |
| --- | --- | --- | ---: |
| `vector_apply_boost` (default) | **9/9** | 1.00 | 0.45 |
| `hybrid_rrf_apply` | **9/9** | 1.00 | 0.46 |
| `union_literal_apply` | **9/9** | 1.00 | 0.46 |
| `union_lexical_apply` | **9/9** | 1.00 | **0.36** |
| `vector_apply` | 7/9 | 0.80 | 0.45 |
| `vector_raw` | 6/9 | 0.80 | 0.36 |
| `lexical_apply` | 5/9 | 0.50 | 0.67 (n=5) |

Four strategies saturate the gate at 9/9. `lexical_apply`'s precision is a
selection effect — it is averaged over only the 5 fixtures where it returned
anything at all.

Three findings matter more than the tie:

1. **The boosts are load-bearing, and this is the first evidence of it.**
   `vector_apply` → `vector_apply_boost` moves 7/9 → 9/9 and Hit@K 0.80 → 1.00.
   The old six-fixture set could not show this; it had `vector_apply` and
   `vector_apply_boost` tied at 4/4, with plain `vector_apply` scoring *higher*
   mean precision. `test-10a-measured-values` and `transport-bolt-vocabulary`
   both fail without boosts and pass with them.
2. **A full-text arm actively hurts.** `union_lexical_apply` costs 0.09 mean
   precision (0.45 → 0.36) for zero recall gain. It drops
   `serial-inside-door-lock-tsp` precision from 1.00 to 0.20. Without IDF the
   arm contributes noise, exactly as the probe predicted.
3. **The dense arm already recalls rare literals.** `vector_apply`, with no
   literal arm and no boosts, passes both part-number fixtures. BGE embeddings
   retrieve `W10804741` from a column-mangled table row on cosine similarity
   alone, so there is no recall gap for a lexical arm to close. This contradicts
   the premise that motivated the experiment.

## Decision

1. **Keep `vector_apply_boost` as the production default.** Confirmed a second
   time, now against 9 hard fixtures instead of 4.
2. **Do not adopt a Postgres full-text arm.** Measurably worse precision, no
   recall gain, and the root cause (no IDF in `ts_rank_cd`) is not tunable.
   Adopting one would require a BM25-capable index, which is out of scope.
3. **Keep `union_literal_apply` in the bake-off, unadopted.** It is
   precision-neutral and recall-neutral today, so it earns no place in
   production. It is retained because it is the principled generalisation of the
   four side doors, and it is the candidate to revisit if corpus growth dilutes
   dense recall over rare tokens — the failure mode it is built for.
4. **Correct the ADR-0011 record.** Its stated reason for rejecting hybrid
   ("hybrid diluted the ACU LED bulletin hit") no longer reproduces. Hybrid is
   rejected on precision and operational cost, not on recall.
5. Re-run `repair-corpus bench-retrieve --write` when the corpus, chunker, or
   embedding model changes, and re-check finding 3 in particular.

## Consequences

- The release gate is meaningfully stronger: 9 hard fixtures covering
  rare-literal recall and one term-mismatch counterweight.
- The boosts now have measured justification rather than case-by-case
  motivation, which raises the bar for removing any of them.
- Two strategies are carried in the bake-off that are not used in production.
  That is deliberate cost: they are the controls that make "we did not adopt
  hybrid" a measurement rather than an assumption.
- `lexical_fetch` keeps its `plainto_tsquery` AND semantics so ADR-0011's
  numbers stay reproducible. `lexical_or_fetch` is a separate function rather
  than a fix in place, which means the known-bad arm stays in the tree.
- The bake-off still understates production. `run_strategy` omits
  `connector_fetch`, `reference_fetch`, and `manual_rev_fetch`, so
  `bench-retrieve` measures retrieval cores, not what `ask` and `diagnose`
  actually run.
