# Embedder A/B: BGE-base vs Jasper-Token-Compression-600M

- Lockfile: `uv.lock@95db48c278cc`
- LLM_MODEL: `gpt-4o-mini`
- JUDGE_LLM_MODEL: `gpt-4.1-mini-2025-04-14`
- EMBEDDING_MODEL: `BAAI/bge-base-en-v1.5`

K=8 · overfetch=40 · BGE=`BAAI/bge-base-en-v1.5` · Jasper=`infgrad/Jasper-Token-Compression-600M`

Production `search()` / `EMBEDDING_MODEL` **unchanged**. Jasper index is experimental (in-memory + drafts cache).
Insufficient evidence for a production change until hard-pass and IR metrics clearly beat the baseline.

## Indexing cost (one-time)

| Arm | chunks | dims | embed wall ms | cache | model | notes |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `bge_vector_apply_boost` | 2327 | 768 | 0 | hit | `BAAI/bge-base-en-v1.5` | Postgres active_chunks vectors (production) |
| `jasper_vector_apply_boost` | 2327 | 2048 | 4788813 | miss | `infgrad/Jasper-Token-Compression-600M` | wrote jasper_a55b2577c205180a.npy |

Local embed API cost is **$0** for both arms. Jasper is ~0.6B params (heavier CPU than BGE-base ~110M) and emits **2048-d** vectors.

## Hard-fixture summary

- **`bge_vector_apply_boost`**: 14/14 hard fixtures passed
- **`jasper_vector_apply_boost`**: 14/14 hard fixtures passed

## Aggregate IR + latency

| Arm | Hit@K | mean MRR | mean nDCG@K | mean Prec@K | mean lat ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bge_vector_apply_boost` | 1.00 | 0.791 | 0.843 | 0.470 | 167 |
| `jasper_vector_apply_boost` | 0.93 | 0.671 | 0.735 | 0.430 | 429 |

## Per fixture (pass / rank signals)

### `acu-led-step-10` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 0.333 | 1024 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 554 | ok |

### `door-locks-wont-run-wrong-platform` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | n/a | n/a | 141 | ok |
| `jasper_vector_apply_boost` | PASS | n/a | n/a | 458 | ok |

### `f5e2-front-load-not-top-load` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 178 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 416 | ok |

### `error-code-f6e1` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 0.500 | 136 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.500 | 364 | ok |

### `connector-j36-motor-harness` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 113 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 388 | ok |

### `part-number-door-lock` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 0.500 | 133 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.143 | 419 | ok |

### `transport-bolt-vocabulary` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 0.200 | 114 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.250 | 406 | ok |

### `serial-inside-door-lock-tsp`

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 99 | ok |
| `jasper_vector_apply_boost` | FAIL | no | 0.000 | 378 | must_cite missing 'W11395614'; got [] |

### `serial-outside-door-lock-tsp`

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | n/a | n/a | 103 | ok |
| `jasper_vector_apply_boost` | PASS | n/a | n/a | 448 | ok |

### `part-number-pressure-switch`

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 143 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.500 | 445 | ok |

### `test-10a-measured-values`

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 97 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.333 | 352 | ok |

### `tech-sheet-page1-by-pub` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 96 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 418 | ok |

### `manual-rev-b-acu-led` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 121 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 396 | ok |

### `f5e2-tech-sheet-not-kb` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 0.333 | 128 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 0.333 | 588 | ok |

### `publication-what-is-w11375982` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 98 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 466 | ok |

### `adjacent-model-parts-exclude` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | n/a | n/a | 96 | ok |
| `jasper_vector_apply_boost` | PASS | n/a | n/a | 438 | ok |

### `maytag-mhw-platform-manual` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 94 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 390 | ok |

### `synth-owners-manual-supersession` (hard)

| Arm | pass | Hit@K | MRR | lat ms | detail |
| --- | --- | --- | ---: | ---: | --- |
| `bge_vector_apply_boost` | PASS | yes | 1.000 | 94 | ok |
| `jasper_vector_apply_boost` | PASS | yes | 1.000 | 397 | ok |

## Reading the result

- Prefer equal-or-better hard pass **and** better MRR/nDCG before considering a cutover.
- Jasper needs a full re-ingest + 2048-d pgvector migration to ship; this bake-off does not do that.
- Query latency includes Jasper encode on CPU; BGE uses the warm local model + Postgres HNSW.

