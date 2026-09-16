# Semantic embed bake-off (experiment)

- Lockfile: `uv.lock@95db48c278cc`
- LLM_MODEL: `gpt-4o-mini`
- JUDGE_LLM_MODEL: `gpt-4.1-mini-2025-04-14`
- EMBEDDING_MODEL: `BAAI/bge-base-en-v1.5`

Document: `installation-instructions-w11156977` · K=5 · budget=480 · embedder=`BAAI/bge-base-en-v1.5`

Production `search()` unchanged. Experiment fixtures only — not the S4 gate.
Insufficient evidence for a production change (recorded 2026-09-16).

## Indexing cost (one-time)

| Arm | units | vectors | embed calls | embed tokens | wall ms | DB reuse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `semantic_reps` | 9 | 25 | 0 | 2190 | 49 | 25 |
| `source_text_windows` | 9 | 29 | 29 | 11558 | 18472 | 0 |
| `source_text_truncate` | 9 | 9 | 9 | 3580 | 6903 | 0 |

### Curator LLM cost (representations arm only, estimate)

- Model: `gpt-4o-mini`
- Prompt tokens ≈ 11,616
- Completion tokens ≈ 2,190
- USD ≈ **$0.0509** (in $2.5/MTok, out $10.0/MTok)
- Estimate only — extract/window arms skip this curator LLM call. Local BGE embed cost is $0 for all arms.

Local BGE embedding is **$0** API cost for every arm.

## Query metrics

| Arm | hard pass | Hit@K | mean MRR | mean latency ms |
| --- | ---: | ---: | ---: | ---: |
| `semantic_reps` | 8/8 | 1.00 | 0.713 | 140.9 |
| `source_text_windows` | 8/8 | 1.00 | 0.754 | 141.2 |
| `source_text_truncate` | 8/8 | 1.00 | 0.781 | 137.7 |

## Per fixture

### `transport-bolt-shipping-vocab`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 2 | 0.500 | 91.0 | 008-installation-instructions-french, 005-installation-instructions, 009-complete-installation-checklist |
| `source_text_windows` | PASS | 2 | 0.500 | 90.7 | 005-installation-instructions-b, 005-installation-instructions, 002-installation-requirements-tools-and-parts |
| `source_text_truncate` | PASS | 1 | 1.000 | 88.1 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |

### `remove-transport-bolts-oem`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 1 | 1.000 | 67.1 | 005-installation-instructions, 008-installation-instructions-french, 005-installation-instructions-b |
| `source_text_windows` | PASS | 1 | 1.000 | 66.4 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |
| `source_text_truncate` | PASS | 1 | 1.000 | 62.5 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |

### `connect-drain-hose`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 2 | 0.500 | 77.5 | 001-washer-installation-instructions, 005-installation-instructions-b, 005-installation-instructions |
| `source_text_windows` | PASS | 1 | 1.000 | 77.8 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |
| `source_text_truncate` | PASS | 1 | 1.000 | 76.5 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |

### `tools-and-parts`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 1 | 1.000 | 120.9 | 002-installation-requirements-tools-and-parts, 001-washer-installation-instructions, 006-washer-safety-and-installation-requirements-fren |
| `source_text_windows` | PASS | 1 | 1.000 | 122.1 | 002-installation-requirements-tools-and-parts, 005-installation-instructions, 005-installation-instructions-b |
| `source_text_truncate` | PASS | 1 | 1.000 | 117.3 | 002-installation-requirements-tools-and-parts, 005-installation-instructions, 005-installation-instructions-b |

### `level-washer`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 2 | 0.500 | 229.8 | 001-washer-installation-instructions, 005-installation-instructions-b, 008-installation-instructions-french |
| `source_text_windows` | PASS | 1 | 1.000 | 229.3 | 005-installation-instructions-b, 005-installation-instructions, 002-installation-requirements-tools-and-parts |
| `source_text_truncate` | PASS | 2 | 0.500 | 225.2 | 005-installation-instructions, 005-installation-instructions-b, 002-installation-requirements-tools-and-parts |

### `installation-checklist`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 1 | 1.000 | 314.0 | 009-complete-installation-checklist, 001-washer-installation-instructions, 002-installation-requirements-tools-and-parts |
| `source_text_windows` | PASS | 5 | 0.200 | 314.7 | 002-installation-requirements-tools-and-parts, 001-washer-installation-instructions, 005-installation-instructions-b |
| `source_text_truncate` | PASS | 4 | 0.250 | 311.4 | 002-installation-requirements-tools-and-parts, 001-washer-installation-instructions, 008-installation-instructions-french |

### `shipping-materials-requirements`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 5 | 0.200 | 136.7 | 008-installation-instructions-french, 009-complete-installation-checklist, 005-installation-instructions |
| `source_text_windows` | PASS | 3 | 0.333 | 136.0 | 005-installation-instructions-b, 005-installation-instructions, 002-installation-requirements-tools-and-parts |
| `source_text_truncate` | PASS | 2 | 0.500 | 132.7 | 005-installation-instructions, 002-installation-requirements-tools-and-parts, 005-installation-instructions-b |

### `drain-hose-standpipe`

| Arm | pass | rank | MRR | ms | top unit_keys |
| --- | --- | ---: | ---: | ---: | --- |
| `semantic_reps` | PASS | 1 | 1.000 | 90.1 | 005-installation-instructions-b, 007-electrical-specifications-and-drain-system-frenc, 002-installation-requirements-tools-and-parts |
| `source_text_windows` | PASS | 1 | 1.000 | 92.9 | 005-installation-instructions-b, 002-installation-requirements-tools-and-parts, 005-installation-instructions |
| `source_text_truncate` | PASS | 1 | 1.000 | 88.1 | 005-installation-instructions-b, 005-installation-instructions, 002-installation-requirements-tools-and-parts |

## Reading the result

- Prefer higher hard pass / Hit@K / MRR at similar latency.
- `source_text_windows` pays more **index** embed time/tokens; query latency stays comparable (one query embed + cosine).
- `semantic_reps` adds a **paid curator LLM** step once per promote; extract arms skip that.
- `source_text_truncate` shows the failure mode of embedding a long extract without windowing.
