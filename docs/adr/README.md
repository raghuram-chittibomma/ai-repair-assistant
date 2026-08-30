# Architecture Decision Records

One record per significant decision: the context, the options genuinely
considered, what was chosen, why, and what it costs. A decision without a
recorded cost has usually not been thought through.

**North star:** [../CHARTER.md](../CHARTER.md). Before accepting an ADR, check
it against the charter. If the decision **deviates**, say so in the ADR and add
a row to the charter’s [Deviations](../CHARTER.md#deviations-from-this-charter)
register.

Records are immutable once accepted. To change a decision, write a new ADR that
supersedes the old one and update the older record's status. ADR-0003 already
supersedes an earlier draft of this project's acquisition design.
ADR-0009 supersedes the embedding provider choice in ADR-0008.

## Phase 1 — Corpus

| ADR | Decision | Driver |
| --- | --- | --- |
| [0001](0001-corpus-manifest-format.md) | Corpus manifest is git-committed YAML, with Croissant as an export | The bytes cannot be redistributed, and every claim must be reviewable in a diff |
| [0002](0002-three-layer-document-identity.md) | Document identity has three layers | PDF byte hashes are unstable by construction, so one hash per document breaks immediately |
| [0003](0003-no-downloader.md) | The repository ships no downloader | Whirlpool's Terms of Use prohibit automated retrieval, notwithstanding a permissive `robots.txt` |
| [0004](0004-applicability-and-precedence.md) | Applicability and precedence are structured data | A correct instruction for the wrong machine is still wrong, and that must be decidable rather than inferred |
| [0005](0005-copyright-separation-and-licence.md) | Three-way copyright separation, Apache-2.0, SPDX, enforced in CI | Free access under right-to-repair law is not a redistribution licence |

## Phase 2 — Parsing

| ADR | Decision | Driver |
| --- | --- | --- |
| [0007](0007-parser-and-chunker.md) | pdfplumber table engine + structured table-row chunking; pypdf fixed-size is the failing control | Tech-sheet error table and F6E1 binding measured in bake-off |
| [0024](0024-hybrid-parse-architecture.md) | Hybrid page router (pdfplumber tables + layout prose); canonical tree; parse quality audit | Multi-column procedures; parser ≠ chunker |
| [0022](0022-contextual-chunk-enrichment.md) | Contextual text enrichment + bounded chunk quality self-check | Opaque numeric rows; headers were metadata-only |

## Phase 3 — Ingestion

| ADR | Decision | Driver |
| --- | --- | --- |
| [0008](0008-incremental-ingestion.md) | Parsed JSONL → Postgres/pgvector; fingerprint skip | Incremental refresh without re-parse; LAN DB |
| [0009](0009-local-open-embeddings.md) | Local `BAAI/bge-base-en-v1.5` (768-d); OpenAI not used for embed | Zero embed cost; OpenAI reserved for LLM only |

## Phase 4 — Retrieval

| ADR | Decision | Driver |
| --- | --- | --- |
| [0010](0010-retrieval-applicability.md) | Over-fetch vectors; filter by applicability; light boosts (**interim default**) | W11395614 / W11375982 cases |
| [0011](0011-retrieval-bakeoff.md) | Bake-off confirms ADR-0010; lexical/hybrid not adopted yet | D4 experiments; F5E2 KB gap |
| [0020](0020-hybrid-retrieval-retest.md) | Hybrid re-tested; default kept at **14/14** hard (product-class gate + synthetics) | Full-text arm still costs precision; boosts more load-bearing |
| [0027](0027-cross-encoder-rerank.md) | **Rejected** — `bge-reranker-base` loses to `vector_apply_boost` (10/14, MRR 0.57, ~36 s mean) | Review R14 / S5 |

## Phase 5 — Grounded Q&A

| ADR | Decision | Driver |
| --- | --- | --- |
| [0012](0012-grounded-qa.md) | Retrieve (ADR-0010) → numbered evidence → OpenAI chat; citations + abstention | Charter Phase 6 |

## Phase 6 — Diagnostic assistant

| ADR | Decision | Driver |
| --- | --- | --- |
| [0013](0013-langgraph-diagnostic.md) | LangGraph retrieve→respond per turn; CLI REPL; smoke scenarios | Charter Phase 7 |

## Phase 7 — Safety and escalation

| ADR | Decision | Driver |
| --- | --- | --- |
| [0014](0014-safety-policy.md) | Deterministic allow/warn/escalate/block; `--audience`; bench-safety fixtures | Charter Phase 8 |
| [0026](0026-streaming-safety-gate.md) | Incremental gate on the streaming path; refuse to stream when the outcome is decided; one shared hazard detector | Review R1 — streamed tokens bypassed the post-LLM gate |

## Phase 8 — Evaluation and observability

| ADR | Decision | Driver |
| --- | --- | --- |
| [0015](0015-qa-eval-logging.md) | `bench-qa` smoke runner; deterministic grader; JSON run logs | Charter Phase 9 (incremental) |
| [0018](0018-langfuse-observability.md) | Self-hosted Langfuse (MIT); opt-in SDK traces; not LangSmith | Charter Phase 9; OSS + D8 |
| [0019](0019-llm-judge-promote.md) | Opt-in `--judge` for prose expect/fails_if; `promote-eval` drafts | Charter Phase 9 maturity |

## Phase 9 — Product surface (API / UI)

| ADR | Decision | Driver |
| --- | --- | --- |
| [0016](0016-http-api-docker.md) | FastAPI `/v1/*`; optional API key; Dockerfile + Compose `api` service | Charter Phase 10 |
| [0017](0017-web-ui-deploy-eval.md) | `/ui` web chat; `deploy-api.ps1`; `bench-candidates` + grading overlay | LAN product use |

## Phase 10 — Product hardening

| ADR | Decision | Driver |
| --- | --- | --- |
| [0021](0021-api-hardening-embedder-sessions.md) | Shared embedder + warmup; in-memory session TTL/max; DB pool; LLM/pool timeouts | Day-to-day LAN reliability |

## Phase 11 — Trace-driven evaluation

| ADR | Decision | Driver |
| --- | --- | --- |
| [0023](0023-trace-driven-eval-mining.md) | `mine-traces`: stamp + window + replay → analysis report; human promote only | Charter Phase 11 / E13 |

## Scope

| ADR | Decision | Driver |
| --- | --- | --- |
| [0025](0025-deferred-scope-multi-user-outcome-curation.md) | Multi-user, product-outcome, and curation-at-scale findings deferred with reopen triggers and detectors; three permanent non-goals named | External review triage ([response](../ARCHITECTURE_REVIEW_RESPONSE.md)); affirms charter D8 |

## Infrastructure

| ADR | Decision | Driver |
| --- | --- | --- |
| [0006](0006-lan-docker-host.md) | Postgres / pgvector run on a shared LAN Docker host; addresses stay local | Shared host already runs other DBs; laptop is not the default runtime; LAN details are not committed |
