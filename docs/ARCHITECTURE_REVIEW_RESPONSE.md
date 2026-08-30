# Response to the external architecture review

**Progress (2026-08-29).** S1 landed: **R1**, **R36**, **R9**, **R10** (disclaimer
wording signed off), **R5**, **R7**, **R8**, **R25** (partial), **R39**.
S2 landed: **R37** lockfile + dated model stamp, **R46** YAML-driven safety
tests, **R26** `bench-safety` in CI, **R45** ADR-0014/E3 wording, **R28**
revision-aware citations, **R4** adversarial set (19% unsafe-recall, 0%
false-escalation; not a CI gate; `policy.py` not retuned). S3 landed: **R38**
synthetic pgvector in CI, **R16** embedding-model guard, **R35** release the
pool connection before generation, **R15** trigram GIN, **R40** manifest cache
with mtime + reload. S4 uses the current 18 fixtures as the decision set
(held-out test waived). **R29** MRR / nDCG / retrieve latency land on that set.
S7 agent-doable items landed: **R33**, **R34**, **R43**, ADR-0025 detectors,
**R19**, **R25** transcript window, **R42** parts-list linkage, **R2** audience
attestation, **R44** trace governance. **R41** feedback UI is deferred.

**Date:** 2026-08-29
**Responds to:** [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) (48 findings, R1–R48)
**Scope:** commit `63a4369` (branch `master`) — the same commit the review read, so
no drift to reconcile.
**Method:** ~20 of the review's strongest claims re-verified directly against the
code before triage. Findings the review marked **[inferred]** are still inferred
here and are marked as needing reproduction before a fix.

> **Companion documents.** [EVAL_FRAMEWORK_GAPS.md](EVAL_FRAMEWORK_GAPS.md) is the
> project's own eval audit and overlaps with review section 4. This document does
> not supersede any ADR; the deferrals in it are recorded in a single new ADR
> (see [Deferral record](#deferral-record)).

---

## Verdict

**The review is accurate and should be worked.** Every claim re-verified held up,
including all four of its P0 items. There is no fabricated finding among those
checked, which is worth stating plainly because it sets the default posture:
findings are accepted unless this document argues otherwise.

Two qualifications shape the plan:

1. **It grades against a standard the charter disclaims.** Several findings are
   marked "Critical (at scale)" and are correct as descriptions of code while
   describing conditions that do not exist — charter **D8** is LAN-only
   single-user, the corpus is one product family, and there are no users. For
   those the right artefact is a written decision with a reopen trigger, not code.
2. **Its central finding is right and is the expensive one.** R12 / R13 / R48 —
   retrieval quality encoded as ~25 constants and ~12 regexes fitted to the same
   fixtures that measure them — is the real finding. R14 (reranking never
   evaluated) is the principled exit. Everything in slices 1–3 below exists to
   make that experiment trustworthy when it happens.

   For the record, since the review cites both numbers without reconciling them:
   `evals/retrieval/fixtures.yaml` holds **18 fixtures, 14 of them `hard: true`**.
   The 14 are the pass/fail gate that `vector_apply_boost` scores 14/14 on; all 18
   become the dev set in slice 4.

---

## Verification log

Re-checked before triage. All confirmed.

| Finding | Claim | Observed |
| --- | --- | --- |
| R1 | Streaming emits ungated tokens | `qa/generate.py:642` yields per-delta `token`; `_trace_gate` at `:660`, after the loop |
| R5 | Default bind is all interfaces | `api/main.py:14` — `REPAIR_API_HOST` defaults to `0.0.0.0` |
| R7 | No input cap | No `max_length` anywhere in `api/` |
| R9 | Inconsistent gate labelling | `safety/gate.py:97-104` — `needs_grounding_citation` returns `ALLOW` with `blocked=True` |
| R10 | No disclaimer in UI | No match for `disclaim\|liability\|not a substitute` in `api/static/index.html` |
| R13 | Corpus literals in retrieval | `retrieval/search.py:306` — `WHEN page = 44 THEN 1`; `:307` ACU regex; `rank.py:281,289`; `qa/context.py:83,89` needles |
| R16 | Embedding model never validated | `embedding_model` written in `ingest/store.py:177,221`; read only as env config — no comparison against stored vectors |
| R26 | No eval in CI | `.github/workflows/ci.yml` runs ruff, manifest validate, pytest, corpus status, copyright guard. No bench, no database |
| R27 | Judge cannot see evidence | `eval/llm_judge.py` `build_judge_user_prompt` — no evidence parameter |
| R28 | Citation match ignores revision | `eval/grading.py:97-105` — `needle in k`, so `W11169652` matches any revision |
| R32 | Sessions capped and evicted | `api/sessions.py:16` — `DEFAULT_SESSION_MAX = 32` |
| R35 | Connection pinned across generation | `api/db_pool.py:12` pool of 4; stream routes take `Depends(get_db)` at `api/app.py:289,383` |
| R36 | Error classes unhandled, detail leaked | Routes catch only `LLMTimeoutError` / `RuntimeError`; bare `except Exception` yields `str(exc)` at `api/app.py:319,422` |
| R37 | No lockfile | No `uv.lock`, `poetry.lock`, or hash-pinned requirements in the tree |
| R39 | No `.dockerignore` | Absent at repo root; `docker/compose.yaml` builds from `..`, and `.env.local` is present there |
| R41 | No feedback signal | No thumbs / rating / feedback markup in `index.html`; no `score` call in `observability/` |
| R43 | No token usage recorded | `observability/langfuse_tracing.py` `generation()` records no usage |
| R38 | No test touches Postgres | No match for `psycopg\|Database(` under `tests/` |

---

## Where this response departs from the review

**R38 is both easier and narrower than described.** The review proposes a pgvector
service container plus "a small seeded fixture corpus." A seeded corpus of
manufacturer text is precisely what the copyright guard exists to prevent, so that
plan as written is unavailable. However `retrieval/synthetic.py` already provides
`ensure_synthetic_ingested`, `load_synthetic_documents`, and
`merge_manifest_with_synthetic` — a copyright-safe seed built for this purpose.
Database-in-CI is therefore very achievable. What it buys is **SQL correctness**
(the `text[]` overlap operators, the `ANY(%s::int[])` casts, the neighbour join in
`connector_fetch`, HNSW behaviour across pgvector versions), **not** retrieval
quality. R26 leans on R38 for more than R38 can deliver.

**R33 is a smaller job than its P4 placement implies.** `parsing/page_classify.py`
already exists with `classify_page` and `looks_like_matrix_page`. Adding
figure-page classification, excluding that garbage text from the index, and
emitting an honest "references Figure 2 on page 26, which this assistant cannot
read" note extends machinery that is already there. This is an *honesty* defect,
not a coverage to-do, and it is promoted accordingly.

**R28 is promoted to an early slice.** The review rates it Medium. An eval that
cannot distinguish `W11169652 Rev B` from `Rev D` makes the revision-precedence
fixtures unable to prove the one capability they exist to prove — which puts a
question mark over retrieval measurements taken downstream of it. It is cheap and
it comes before the measurement work in slice 4.

**R3's remedy conflicts with R26's.** Adding an LLM safety classifier makes the
safety path depend on OpenAI. The safety bench's main virtue as a CI gate is that
it needs neither OpenAI nor Postgres, which is exactly why it is the one bench
that can become a required check. Defence in depth is still the right direction,
but the ADR must resolve this tension explicitly — most likely by keeping the
deterministic arm independently gateable in CI and treating the LLM arm as a
runtime-only augmentation.

**R17 must not be implemented before slice 4.** A minimum similarity threshold is
itself a hand-tuned constant. Adding one now, fitted against the same 14 fixtures,
would be a fresh instance of R12 committed in the course of remediating R12.

**R30's prescription is not available.** The instinct — a 10-case calibration pack
is too small to detect judge drift — is correct. Expanding it to ~100 human-labelled
cases is a manual labelling programme, and inter-annotator agreement is impossible
with a single developer. Judge-model diversity and an abstention option are
achievable; the agreement statistics are not.

---

## Constraint blockers

Items that cannot be delivered as written, with the reason. These are constraints,
not backlog.

| Constraint | Source | Blocks |
| --- | --- | --- |
| Manufacturer documents may never enter git or CI | [CORPUS_LICENSING.md](CORPUS_LICENSING.md), enforced by the copyright-guard job | R26 / R38 as written. CI evals may use synthetic documents or manifest metadata only; real-corpus retrieval quality stays a local manual bench |
| No OpenAI key in CI, and per-run API cost | D1 — API usage is the paid exception | `bench-qa`, `bench-candidates --judge`, and judge calibration can never be required PR checks. Manual or scheduled-with-budget only |
| Zero paid infrastructure; one workstation | Charter | R14's cross-encoder is feasible on CPU but contends with the BGE embedder on the same box. The ADR must report added latency, not only IR gain |
| No users | Project stage | R41 can be built but will accrue no data. R42's call-deflection and part-conversion measures are unmeasurable by construction |
| Single developer / single annotator | Project stage | R30's calibration expansion and any inter-annotator agreement statistic |
| One product family in the corpus | Corpus scope | R11 / R20 recall degradation cannot be demonstrated on the real corpus. Synthetic multi-model evidence only, and the ADR must label it as such |
| Technician status cannot be verified | Product nature | R2's "real verification." Available action is limited to logging the claim and an attestation interstitial |

---

## Disposition of all 48 findings

**Accept** — will be fixed. **Accept (ADR-first)** — needs a written decision with
measured alternatives before code, per the charter. **Reduce** — partially
achievable; the remainder is a constraint blocker. **Reframe** — the observation
is correct but the framing is rejected; recorded as a non-goal. **Defer** —
recorded in the deferral ADR with a reopen trigger.

| ID | Disposition | Slice | Note |
| --- | --- | --- | --- |
| R1 | Accept | S1 | Also correct the ADR-0014 and README claim that the gate always holds |
| R2 | Reduce | S7 | Log the claim + attestation interstitial; verification is a permanent non-goal |
| R3 | Accept (ADR-first) | S7 | Must resolve the CI-independence tension noted above |
| R4 | Accept | S2 | Author the adversarial set *before* touching `policy.py`; report unsafe-recall and false-escalation separately |
| R5 | Accept | S1 | Default `127.0.0.1`; LAN exposure becomes an explicit opt-in |
| R6 | Defer | ADR-0025 | Reopen trigger: deployment stops being single-user LAN. Detector: startup warning when auth is unset and the bind is non-loopback |
| R7 | Reduce | S1 | `max_length` + per-session turn cap achievable; a true spend ceiling needs billing integration — documented budget alert instead |
| R8 | Accept | S1 | Delimit evidence, instruct that evidence is data and never instructions |
| R9 | Accept | S1 | Introduce a distinct action rather than `ALLOW` + `blocked=True` |
| R10 | Accept | S1 | Wording is a product decision — needs owner sign-off, not agent drafting |
| R11 | Accept (ADR-first) | S6 | Denormalise applicability at ingest; keep `document_applies` authoritative. Synthetic multi-model bench first |
| R12 | Accept | S4 | Requires owner-authored held-out fixtures — see slice 4 |
| R13 | Accept | S4/S5 | Removal will regress the scorecard. See [the regression note](#the-r13-regression-is-the-point) |
| R14 | Accept (ADR-first) | S5 | The highest-value missing experiment. Meaningless before S4 |
| R15 | Accept | S3 | Trigram GIN index for the side-door recall paths |
| R16 | Accept | S3 | Startup + ingest assertion; `ingest --force` as the documented migration |
| R17 | Accept | S4 | Deliberately *after* S4 — the threshold is a tuned constant |
| R18 | Accept (ADR-first) | S6 | Query rewriting; also the honest fix for R22 |
| R19 | Accept | S7 | Drift check ("a newer publication references this one") + staleness signal. Tooling is R47 |
| R20 | Accept | S6 | Platform, region, effective date, software version — data is already in the manifest |
| R21 | Accept | S5 | Same accretion as R13; remove alongside it |
| R22 | Accept | S6 | Remove the coercion; fix the underlying retrieval drift |
| R23 | Accept (ADR-first) | S6 | Structured claim→evidence output; precondition for R27 |
| R24 | Reduce | S6 | Langfuse prompt versioning is achievable; automated prompt evals need an OpenAI key — manual/scheduled |
| R25 | Accept | S1 / S6 | `temperature=0` + `max_tokens` in S1; transcript windowing in S6 |
| R26 | Reduce | S2 / S3 | Safety bench + synthetic retrieval smoke can gate. `bench-qa` and judge cannot — no key in CI |
| R27 | Accept | S6 | Evidence to the judge, claim-level entailment, unsupported-claim rate |
| R28 | Accept | S2 | Revision-aware citation matching |
| R29 | Accept | S4 / S7 | MRR / nDCG + latency in S4; token and cost with R43 in S7 |
| R30 | Reduce | S7 | Judge-model diversity and abstention achievable; agreement statistics blocked |
| R31 | Accept (ADR-first) | S7 | Structured state unblocks trajectory evals and gap #7 in the eval audit |
| R32 | Defer | ADR-0025 | Already deferred in ADR-0021; ADR-0025 adds the trigger and a worker-count detector |
| R33 | Accept | S7 | Promoted from P4. Figure classification + honest note; OCR stays deferred per ADR-0024 |
| R34 | Reframe | S7 | Serving Spanish is a non-goal; stop paying the index cost for content with no product value |
| R35 | Accept | S3 | Release the connection before generation |
| R36 | Accept | S1 | Retry with backoff, full error taxonomy, retrieval-only degraded mode, stop echoing `str(exc)` |
| R37 | Accept | S2 | Lockfile + dated model snapshot, both stamped into scorecard headers |
| R38 | Accept | S3 | Via the existing synthetic corpus — see the departure note above |
| R39 | Accept | S1 | `.dockerignore`, non-root container, pre-baked model with `HF_HOME` |
| R40 | Accept | S3 | Cache with explicit invalidation, not a bare `lru_cache` |
| R41 | Accept | S7 | Build it; no data will accrue until there are users, which is fine |
| R42 | Reframe / Defer | S7 | Accounts, ordering, history are non-goals. The parts-number linkage is cheap and worth doing |
| R43 | Accept | S7 | Token usage on generation spans |
| R44 | Accept | S7 | Retention, redaction, and deletion path documented |
| R45 | Accept | S2 | One-line ADR-0014 correction |
| R46 | Accept | S2 | Parameterise the unit test over the YAML fixtures |
| R47 | Defer | S7 / ADR-0025 | Drift check only (with R19). Reopen trigger: corpus past ~50 documents, announced by a `repair-corpus status` notice |
| R48 | Accept | S4 / S5 | The thesis of the review. Addressed by S4 then S5, not by a discrete fix |

---

## Remediation slices

One finding per commit, per the review's rules of engagement. Slices are ordered
so that no measured claim is made before the measurement is trustworthy.

### S1 — defects that are real at any scale

No architectural decision required; none of these depends on corpus size, user
count, or deployment posture.

`R1` streaming gate · `R36` error taxonomy and degraded mode · `R9` gate
labelling · `R10` disclaimer · `R5` loopback default · `R7` input caps ·
`R8` evidence delimiting · `R25` (partial) `temperature=0` and `max_tokens` ·
`R39` build-context hygiene.

R36's uncaught `RateLimitError` is marked **[inferred]** in the review and must be
reproduced by injecting the exception before the fix lands.

### S2 — make the evidence base reproducible

The ADR corpus is this repository's primary claim. Right now its scorecards cannot
be regenerated, and one grader cannot measure what its fixtures assert.

`R37` lockfile + dated model snapshot stamped into scorecards · `R46` fixtures as
the single source · `R26` (partial) safety bench as a required check · `R45` ADR
correction · `R28` revision-aware citation matching · `R4` adversarial safety set
with a false-escalation number.

### S3 — Postgres in CI, and the DB-adjacent defects

`R38` pgvector service container seeded from `synthetic.py` · `R16` embedding-model
guard, now testable against a real database · `R35` connection lifetime ·
`R15` trigram index · `R40` manifest cache.

### S4 — held-out measurement, before any retrieval change

**This slice needs the owner, not an agent.** Authoring held-out fixtures means
reading the corpus and deciding ground truth; the copyright constraint and the
domain knowledge both sit with you.

Freeze the current 18 fixtures as **dev**. Author 30–40 new fixtures as **test**,
never tuned against. Re-report every existing strategy on both. Add `R29`'s MRR /
nDCG and latency. Then `R17`'s relevance floor, chosen against the held-out set.
Begin removing `R13`'s literals here.

The expected output is a dev/test gap. That gap is the finding.

### S5 — the reranker bake-off (`ADR-first`)

`R14` measured on S4's held-out set, against `vector_apply_boost`, reporting IR
gain *and* added latency on the workstation. If it wins, `R13` and `R21`'s
literals and a large part of `R48`'s rule stack are deleted rather than tuned.

### S6 — groundedness and retrieval architecture (`ADR-first`)

`R23` structured output, then `R27` groundedness on top of it · `R11`
applicability pre-filter with `R20`'s remaining four axes · `R18` query rewriting,
which permits removing `R22`'s coercion · `R24` prompt versioning · `R25`
transcript windowing.

### S7 — honesty, product signal, and the deferral record

`R33` figure honesty · `R34` non-English as a non-goal · `R41` feedback capture ·
`R43` token usage · `R44` trace governance · `R19` precedence drift check ·
`R31` structured diagnostic state · `R2` audience claim logging · `R3` safety
defence in depth · `R30` judge diversity · plus the deferral ADR covering
`R6`, `R32`, `R42`, `R47`.

---

## The R13 regression is the point

Removing `WHEN page = 44 THEN 1`, the ACU regex, the `drum light` demotion, and
the eight excerpt needles will very likely drop retrieval below 14/14.

**That regression is the correct outcome and must be published, not repaired.**
The current 14/14 is what a ~25-parameter model scores on 14 observations; the
post-removal number is the first honest baseline this project will have. The
failure mode to guard against is reading the regression as breakage and reaching
for a replacement constant to restore green — which is R12 and R48 recommitted
during their own remediation. If a fix in any slice appears to require a new
hand-tuned constant, that is a stop-and-report condition.

---

## Deferral record

`R6`, `R32`, `R42`, and `R47` — plus the permanent non-goals in `R2`, `R34`, and
part of `R30` — are recorded in
[ADR-0025](adr/0025-deferred-scope-multi-user-outcome-curation.md) rather than one
ADR per finding, since they share one rationale: charter **D8** scopes this to a
single-user LAN deployment with no user population, and each becomes a defect only
when that scope changes.

Each entry carries a **reopen trigger** and, where one is cheap, a **detector** so
the trigger announces itself. That is the direct answer to the review's secondary
theme — that the project is "under-instrumented about decisions it deferred." Three
detectors fall out of it as follow-on work: a startup warning when auth is unset
and the bind is non-loopback (with R5 in S1), a warning when more than one API
worker is configured, and a `repair-corpus status` notice past ~50 documents.

Two clarifications that ADR-0025 makes and this table compresses:

- **R42 is only half deferred.** Accounts and history are deferred; linking a
  concluded diagnosis to the part number in the already-indexed parts list is
  accepted and sits in S7.
- **R32 was already deferred** in ADR-0021 ("Postgres session durability remains
  deferred"). ADR-0025 restates it only to attach the trigger and detector that
  ADR-0021 omitted.
