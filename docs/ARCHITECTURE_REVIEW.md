# Architecture and product review — RAG solution audit

**Date:** 2026-08-29
**Reviewer role:** external RAG solution architect / product owner
**Scope:** whole repository at commit `63a4369` (branch `master`)
**Method:** static read of charter, all 24 ADRs, retrieval / generation / safety /
diagnostic / eval / ingest code, schema, CI, Docker, UI. No code was executed
against a live corpus or database; findings marked **[inferred]** were not
observed at runtime.

> **Companion documents.** This review is deliberately *outside-in* and overlaps
> in places with the project's own [EVAL_FRAMEWORK_GAPS.md](EVAL_FRAMEWORK_GAPS.md).
> Where it does, this document says so and adds what that audit did not cover.
> Nothing here supersedes an ADR; several findings recommend *new* ADRs.
>
> **Maintainer response:** [ARCHITECTURE_REVIEW_RESPONSE.md](ARCHITECTURE_REVIEW_RESPONSE.md)
> re-verifies the strongest claims, records a disposition for all 48 findings, and
> lists the constraints that block specific recommendations.

---

## How to use this document (read this first if you are an agent)

This is a review, not a task list to execute top to bottom. Working through it
mechanically will make the codebase worse.

**Rules of engagement:**

1. **One finding per branch and per commit.** Several findings are architectural
   and deserve an ADR before code. Do not batch unrelated fixes.
2. **Do not tune against the existing eval fixtures.** Finding
   [R12](#r12-the-ranking-boosts-are-the-retrieval-system-and-they-are-fitted-to-the-gate-that-measures-them)
   is that the system is already over-fitted to
   `evals/retrieval/fixtures.yaml`. Adding a regex or a boost constant to make a
   named fixture pass is the failure mode this review is warning about, not the
   remedy. If a change requires a new hand-tuned constant, stop and say so.
3. **Findings marked `ADR-first`** must not be implemented before a written
   decision record with alternatives and measured evidence, per the charter's
   *Evidence-Driven Architecture* section.
4. **Confirm before assuming.** Line references were accurate at the commit
   above; re-read the file before editing. Where a finding says **[inferred]**,
   reproduce the behaviour first — do not fix an unconfirmed defect.
5. **Preserve the good parts.** The manifest provenance model, the applicability
   and precedence concept, the ADR discipline, the copyright guard, and the
   deterministic-grader-first posture are strengths. Do not refactor them away in
   pursuit of an item below. See [Appendix A](#appendix-a--what-is-genuinely-strong).
6. **Scope discipline.** Some findings (accounts, parts ordering, i18n) are
   product decisions for a human owner, not agent work. They are recorded for
   completeness and flagged `product-decision`.

**Suggested first slice** (highest value, lowest architectural risk):
`R1` → `R36` → `R16` → `R26` → `R38` → `R27`.

---

## Executive summary

The engineering standard here is above average for RAG systems: decisions are
recorded, alternatives are measured, the corpus study is genuinely rigorous, and
the project's own gap audit is unusually honest. The findings below are not
"basics were missed."

The recurring structural problem is this:

> **Retrieval quality, prompt behaviour, and safety policy are all encoded as
> hand-written regexes and tuned constants, fitted against the same small example
> set that is used to measure them — and none of it runs automatically.**

That produces a system which *measures* well and *generalises* poorly, and which
has no mechanism to notice when a recorded conclusion stops being true. A second
product family, a second brand, or a real user population will expose it.

The secondary theme: the project is well-reasoned about decisions it **made** and
under-instrumented about decisions it **deferred**. Deferred items are documented
honestly in ADRs, but nothing detects the moment a deferral becomes a defect.

### Verdict by dimension

| Dimension | Verdict | Headline finding |
| --- | --- | --- |
| Technique selection | Rigorous but incomplete | Reranking never evaluated; the ranking function itself was never bake-offed ([R12](#r12-the-ranking-boosts-are-the-retrieval-system-and-they-are-fitted-to-the-gate-that-measures-them), [R14](#r14-reranking-was-a-charter-listed-candidate-and-was-never-evaluated)) |
| Retrieval / context | Works at current scale only | Applicability is a post-ANN Python filter, not a pre-filter ([R11](#r11-applicability-is-applied-after-a-global-ann-fetch)) |
| Agent prompt | Accreting eval fixes | Corpus literals in the system prompt; an explicit anti-abstain coercion ([R21](#r21-corpus-specific-literals-and-brand-are-hardcoded-in-prompts), [R22](#r22-the-abstain-override-coerces-the-model-past-its-own-refusal)) |
| Evals | Mature benches, no gate | Nothing runs in CI; no groundedness metric anywhere ([R26](#r26-critical-no-eval-runs-automatically), [R27](#r27-critical-there-is-no-groundedness-or-faithfulness-metric)) |
| Guardrails | Defeated on the default path | Streaming delivers ungated text before the safety gate runs ([R1](#r1-critical-the-streaming-path-bypasses-the-post-llm-safety-gate)) |
| Scalability | Single-user by construction | ~4 concurrent users; DB connection held across the LLM call ([R35](#r35-a-pooled-db-connection-is-held-for-the-entire-llm-generation)) |
| Sustainability | Curation-bound | Manifest authoring is manual with no tooling; rules accrete and never retire ([R19](#r19-precedence-depends-entirely-on-hand-authored-relationship-edges), [R48](#r48-every-new-failure-adds-a-rule-and-rules-never-retire)) |
| Reproducibility | Not achieved | No lockfile and an unversioned model alias — the ADR scorecards cannot be regenerated ([R37](#r37-no-dependency-lockfile--the-adr-evidence-cannot-be-reproduced)) |
| Product / business | Largely unaddressed | No user feedback signal, no outcome measure, no disclaimer ([R41](#r41-critical-product-there-is-no-user-feedback-signal-anywhere-in-the-product), [R42](#r42-the-user-journey-has-no-outcome), [R10](#r10-critical-no-disclaimer-or-liability-language-in-the-ui)) |

### Priority stack

**P0 — ship-blocking before a real user touches this**
`R1` streaming bypasses the safety gate ·
`R27` no groundedness check ·
`R10` no disclaimer / liability text ·
`R36` unhandled LLM error classes with no degraded mode

**P1 — blocks the "production quality, not demo quality" claim**
`R37` no lockfile (evidence not reproducible) ·
`R38` no database in CI (the critical SQL is never executed) ·
`R26` no evals in CI ·
`R35` DB connection held across generation ·
`R16` embedding-model change silently corrupts the index

**P2 — blocks the second product family**
`R11` post-ANN applicability ·
`R20` four of six applicability axes unimplemented ·
`R12` / `R13` fixture-fitted ranking ·
`R14` no reranker experiment ·
`R15` unindexed regex scans ·
`R47` manifest curation has no tooling

**P3 — blocks knowing whether the product works**
`R41` no user feedback ·
`R29` no rank-sensitive IR metrics, no latency / token / cost ·
`R30` judge design ·
`R43` no cost model

**P4 — domain honesty**
`R33` wiring diagrams and figures are invisible, silently, in the mode that most needs them

---

## Finding index

| ID | Severity | Area | Finding |
| --- | --- | --- | --- |
| [R1](#r1-critical-the-streaming-path-bypasses-the-post-llm-safety-gate) | **Critical** | Guardrails | Streaming path bypasses the post-LLM safety gate |
| [R2](#r2-audience-is-a-client-controlled-string) | High | Guardrails | Audience tier is self-asserted by the client |
| [R3](#r3-regex-is-the-sole-safety-classifier) | High | Guardrails | Regex is the sole safety classifier |
| [R4](#r4-safety-fixtures-test-the-regex-against-sentences-written-for-the-regex) | High | Evals | Safety fixtures are non-adversarial; no false-positive metric |
| [R5](#r5-api-auth-fails-open-and-the-server-binds-to-all-interfaces-by-default) | High | Security | Auth fails open; default bind is `0.0.0.0` |
| [R6](#r6-diagnostic-sessions-have-no-ownership-binding) | Medium | Security | Sessions have no ownership binding |
| [R7](#r7-no-rate-limit-input-cap-or-cost-ceiling) | High | Ops | No rate limit, input cap, or cost ceiling |
| [R8](#r8-prompt-injection-is-not-considered-anywhere) | Medium | Guardrails | Prompt injection not considered; KB pages come from a third-party mirror |
| [R9](#r9-gate-result-labelling-is-internally-inconsistent) | Low | Guardrails | `ALLOW` + `blocked=True` skews safety telemetry |
| [R10](#r10-critical-no-disclaimer-or-liability-language-in-the-ui) | **Critical** | Product / legal | No disclaimer, warranty-voiding notice, or assumption-of-risk text |
| [R11](#r11-applicability-is-applied-after-a-global-ann-fetch) | **Critical (at scale)** | Retrieval | Applicability filtering happens after a global top-40 ANN fetch |
| [R12](#r12-the-ranking-boosts-are-the-retrieval-system-and-they-are-fitted-to-the-gate-that-measures-them) | High | Retrieval | ~25 tuned constants fitted to 14 binary fixtures; no held-out set |
| [R13](#r13-corpus-specific-literals-are-baked-into-retrieval-sql-and-ranking) | High | Retrieval | Fixture answers (`page = 44`) written into the retriever |
| [R14](#r14-reranking-was-a-charter-listed-candidate-and-was-never-evaluated) | High | Technique | Reranking never bake-offed — the principled replacement for R12/R13 |
| [R15](#r15-code-and-connector-recall-run-unindexed-regex-scans) | High | Scale | `text ~* …` sequential scans on every query, four side-doors |
| [R16](#r16-changing-the-embedding-model-silently-corrupts-the-index) | High | Correctness | `embedding_model` is written and never read |
| [R17](#r17-no-relevance-floor-and-weak-context-budget-discipline) | Medium | Retrieval | Top-8 shipped unconditionally; hardcoded excerpt needles |
| [R18](#r18-multi-turn-retrieval-has-no-query-rewriting) | Medium | Retrieval | Last three user turns concatenated raw; coreference unresolved |
| [R19](#r19-precedence-depends-entirely-on-hand-authored-relationship-edges) | High | Sustainability | A missing `corrects` edge silently cites superseded guidance |
| [R20](#r20-only-two-of-your-own-six-applicability-axes-are-enforced) | High | Retrieval | Platform, region, effective date, software version unimplemented |
| [R21](#r21-corpus-specific-literals-and-brand-are-hardcoded-in-prompts) | Medium | Prompt | Publication numbers in the system prompt; brand hardcoded |
| [R22](#r22-the-abstain-override-coerces-the-model-past-its-own-refusal) | High | Prompt / safety | Re-prompt with "CRITICAL: … Do NOT abstain" |
| [R23](#r23-citation-binding-is-recovered-by-regex-not-guaranteed-by-structure) | High | Prompt | No structured output; `[n]` scraped from free text |
| [R24](#r24-no-prompt-versioning-and-no-prompt-evals) | Medium | Prompt | Prompt tests assert substrings; Langfuse prompt management unused |
| [R25](#r25-generation-call-hygiene) | Medium | Prompt | `temperature=0.2`, no `max_tokens`, model alias, unbounded transcript |
| [R26](#r26-critical-no-eval-runs-automatically) | **Critical** | Evals | CI runs lint/tests/manifest only; every bench is manual |
| [R27](#r27-critical-there-is-no-groundedness-or-faithfulness-metric) | **Critical** | Evals | Citation identity is checked; citation correctness is not. Judge never sees the evidence |
| [R28](#r28-citation-matching-is-bidirectional-substring-matching) | Medium | Evals | `must_cite: W11169652` passes for any revision |
| [R29](#r29-missing-metrics-against-the-charters-own-list) | Medium | Evals | No MRR / nDCG; no latency, token, cost, or failure-rate metrics |
| [R30](#r30-llm-judge-design-issues) | Medium | Evals | Single judge, same model family, binary verdict, thin human agreement |
| [R31](#r31-the-diagnostic-workflow-has-no-structured-state) | High | Workflow | No hypotheses / ruled-out / observations; blocks trajectory evals |
| [R32](#r32-sessions-are-in-memory-capped-at-32-and-lru-evicted) | High | Scale | 33rd concurrent user silently evicts an active session |
| [R33](#r33-the-system-cannot-see-figures-or-wiring-diagrams-and-does-not-say-so) | High | Coverage | No image / figure / OCR path; garbage figure text is embedded |
| [R34](#r34-spanish-and-french-content-is-ingested-and-unusable) | Medium | Product | Non-English chunks are index weight with no product value |
| [R35](#r35-a-pooled-db-connection-is-held-for-the-entire-llm-generation) | High | Scale | Pool of 4, each connection pinned for the whole generation |
| [R36](#r36-critical-no-retry-unhandled-llm-error-classes-and-no-degraded-mode) | **Critical** | Resilience | `RateLimitError` → HTTP 500; no fallback to retrieval-only |
| [R37](#r37-no-dependency-lockfile--the-adr-evidence-cannot-be-reproduced) | High | Reproducibility | Version ranges only; `gpt-4o-mini` alias not a dated snapshot |
| [R38](#r38-270-tests-and-none-touch-postgres) | High | Testing | The five hand-written SQL queries are never executed in CI |
| [R39](#r39-build-context-leaks-copyrighted-pdfs-and-secrets-over-plaintext-tcp) | High | Security | No `.dockerignore`; documented `tcp://…:2375` workflow; root container |
| [R40](#r40-the-manifest-is-re-parsed-from-disk-on-every-request) | Low | Scale | `manifest.load()` uncached, O(corpus) per request |
| [R41](#r41-critical-product-there-is-no-user-feedback-signal-anywhere-in-the-product) | **Critical (product)** | Product | No thumbs, no scores; trace mining only finds six known regexes |
| [R42](#r42-the-user-journey-has-no-outcome) | High | Product | No resolution capture, no parts link, no accounts, no history |
| [R43](#r43-no-cost-model) | Medium | Product / ops | Langfuse generation spans record no token usage |
| [R44](#r44-no-data-governance-for-traces) | Medium | Privacy | Serial + symptoms + free text retained with no redaction or retention policy |
| [R45](#r45-adr-0014-overclaims-ci-enforcement) | Low | Docs | "enforced in CI today" vs. E3 "skipped" |
| [R46](#r46-safety-fixtures-are-duplicated-by-hand-in-unit-tests) | Low | Testing | Two copies of the same cases will drift |
| [R47](#r47-manifest-curation-is-a-content-ops-program-with-no-tooling) | High | Sustainability | ~100 lines of hand-authored YAML per document, no bootstrap, no drift check |
| [R48](#r48-every-new-failure-adds-a-rule-and-rules-never-retire) | High | Sustainability | Superlinear maintenance cost; rules interact |

---

## 1. Guardrails and safety

### R1 (Critical): the streaming path bypasses the post-LLM safety gate

**Where:** `src/repair_assistant/qa/generate.py:640` (token loop) and `:660`
(gate); same shape in `src/repair_assistant/diagnostic/graph.py`
(`diagnose_turn_stream`); consumer at
`src/repair_assistant/api/static/index.html:656`.

**Evidence:** `ask_stream` yields `{"type": "token", "text": delta}` for every
delta as it arrives from OpenAI. `_trace_gate(...)` runs *after* the loop
completes. The browser writes each token into the DOM immediately
(`streamEl.querySelector(".body").textContent = assembled`) and only swaps in the
gated text on the `done` event.

**Why it matters:** the architecture's central safety claim — a deterministic
gate that enforces policy "even if the model oversteps" (ADR-0014, decision 4) —
does not hold on the path users actually use. An owner asking a live-voltage
question sees the full step-by-step walkthrough render token by token, then
watches it be replaced by an escalation notice. The unsafe content was delivered;
any client, screen recording, or network capture retains it. The non-streaming
`/v1/ask` is correct; the default UI path is not.

**Direction (not prescriptive):** buffer deltas to a safe boundary and gate
incrementally; or classify pre-generation and refuse to stream for
`escalate` / `block` assessments; or stream into a hidden buffer and reveal only
gated content. Any of these preserves perceived latency.

**Acceptance:** a test that drives `ask_stream` with an LLM stub emitting a
known-unsafe procedural answer for an `owner` audience and asserts that **no**
`token` event contains the unsafe substrings — the same assertions
`evals/safety/fixtures.yaml` already makes via `sample_must_not_contain`.

---

### R2: audience is a client-controlled string

**Where:** `src/repair_assistant/api/schemas.py`
(`audience: Literal["owner","technician"]`), UI dropdown.

The entire safety model is audience-tiered, and the tier is asserted by the
caller with no attestation, no logging of the claim, and no differential
treatment. Any owner selects "Technician" and receives full live-voltage TEST
procedures.

**Direction:** at minimum record the claim in the trace and in any audit log, and
show an explicit interstitial attestation. Real verification is a
`product-decision`, but an unlogged, unchallenged self-assertion is weaker than
the ADR implies.

---

### R3: regex is the sole safety classifier

**Where:** `src/repair_assistant/safety/policy.py`.

ADR-0014's premise is that the LLM must not be the *sole* authority on repair
risk. The implementation made **regex** the sole authority, which has the
opposite failure mode: zero paraphrase robustness, English-only, brittle to
misspelling and indirection. `bypass the door lock` is caught; *"how do I get the
door open without the latch working"* and *"what's the trick to make it spin with
the door open"* are not.

**Direction (`ADR-first`):** defence in depth — regex **∪** a cheap LLM safety
classifier, taking the maximum severity, so a paraphrase is caught by one arm and
a jailbreak of the classifier is caught by the other. This satisfies the charter
better than either alone. Requires an ADR with measured recall on R4's fixtures.

---

### R4: safety fixtures test the regex against sentences written for the regex

**Where:** `evals/safety/fixtures.yaml` — 15 cases.

Every case is a direct phrasing that matches a pattern. There is not one
paraphrase, misspelling, indirect framing, or non-English case. This measures
**pattern coverage**, not safety recall. There are also only two `allow`
fixtures, so **over-escalation is unmeasured** — and over-escalation silently
destroys product usefulness (an owner escalated for "why won't my washer drain"
stops using the product).

**Direction:** ~30 adversarial paraphrases and indirect framings plus ~20 benign
controls. Report two numbers: unsafe-recall and false-escalation rate. Author the
adversarial set **before** touching `policy.py`, so it is a held-out measurement
rather than a description of the regexes.

---

### R5: API auth fails open, and the server binds to all interfaces by default

**Where:** `src/repair_assistant/api/app.py:164`
(`if expected and x_api_key != expected`) and
`src/repair_assistant/api/main.py` (`REPAIR_API_HOST` default `0.0.0.0`);
`docs/DEPLOYMENT.md` documents an **empty** `REPAIR_API_KEY` as the default.

LAN-only is a legitimate documented constraint (charter D8). Binds-to-all **plus**
auth-disabled-by-default is the combination that turns one firewall
misconfiguration into an open endpoint spending your OpenAI budget. Config
absence should not mean "no authentication."

**Direction:** default the bind to `127.0.0.1` so exposure is a deliberate act;
keep the LAN workflow as an explicit opt-in env var. Cheap, non-breaking for the
documented setup.

---

### R6: diagnostic sessions have no ownership binding

**Where:** `src/repair_assistant/api/sessions.py`.

Sessions are keyed by UUID4 with no association to a caller. Any client holding a
session id can continue anyone's diagnosis. Unguessable is not the same as
authorised. Low impact under D8; a latent multi-tenant defect the moment the
deployment posture changes.

---

### R7: no rate limit, input cap, or cost ceiling

`question: str` and `message: str` in `src/repair_assistant/api/schemas.py` have
**no `max_length`**. There is no rate limiting, no per-session turn cap, no token
budget, and no spend alert. One client can drive unbounded third-party spend, and
one very large input can be forwarded verbatim to OpenAI.

---

### R8: prompt injection is not considered anywhere

`grep -rn "injection" docs/ src/` returns nothing. Retrieved evidence text is
interpolated verbatim into the prompt. The MHTML knowledge-base pages come from a
**third-party mirror** (`provenance.access_method: third_party_mirror` in the
manifests), which is a genuine untrusted-content channel.

Likelihood is low and the mitigation is cheap: delimit evidence explicitly and
instruct the model that evidence is data, never instructions. "We never
considered it" is a weak answer in a production review.

---

### R9: gate result labelling is internally inconsistent

**Where:** `src/repair_assistant/safety/gate.py` — the
`needs_grounding_citation` branch returns `action=SafetyAction.ALLOW` with
`blocked=True`. Any telemetry or eval that groups by `safety_action` will
under-count these interventions.

---

### R10 (Critical): no disclaimer or liability language in the UI

`grep -i "disclaim\|liability\|not a substitute"` over
`src/repair_assistant/api/static/index.html` returns nothing.

For a product giving consumers electrical and mechanical repair guidance there is
no "not a substitute for a qualified technician", no **warranty-voiding notice**
(directly relevant — `warranty-w11349439` is in your own corpus, and DIY repair
can void it), and no assumption-of-risk text. This is the first item a legal
review flags and it costs one paragraph plus a first-run acknowledgement.

`product-decision` on wording; the *absence* is a defect regardless.

---

## 2. Retrieval and context construction

### R11: applicability is applied *after* a global ANN fetch

**Where:** `src/repair_assistant/retrieval/search.py` `vector_fetch` (orders by
cosine across the whole `chunks` table, `LIMIT overfetch`), then
`src/repair_assistant/retrieval/rank.py` `filter_and_rank` drops inapplicable
documents **in Python**.

This works only because the corpus is one product family. With 50 models the
global top-40 neighbours will be dominated by other models' near-identical text;
applicable chunks get filtered out and the user sees "no evidence found" for
questions the corpus *can* answer. Recall degrades silently and non-linearly with
corpus growth.

**Root cause is architectural:** applicability lives in YAML, so it cannot be a
SQL predicate. `documents` and `chunks` carry no `model_patterns`, `doc_type`,
`authority_tier`, or serial-range columns
(`src/repair_assistant/ingest/sql/001_init.sql`).

**Direction (`ADR-first`):** denormalise applicability onto the chunk/document
rows at ingest time (the manifest stays the source of truth) and pre-filter before
the ANN scan. pgvector supports filtered search; this is the standard pattern.
Keep the Python `document_applies` as the authoritative, testable decision
function — the SQL predicate is a *recall pre-filter*, not a replacement.

**Acceptance:** a bench that ingests a synthetic multi-model corpus (10× current
size, other models' documents added) and shows Hit@K on the existing hard
fixtures does not degrade. This test does not exist today and should be written
**before** the change, as the evidence the ADR needs.

---

### R12: the ranking boosts *are* the retrieval system, and they are fitted to the gate that measures them

**Where:** `src/repair_assistant/retrieval/rank.py`, lines ~200–330.

ADR-0020 reports the decisive fact and walks past it: `vector_apply` →
`vector_apply_boost` moves **8/14 → 14/14**. So the embedding is not what makes
retrieval work; roughly **25 hand-chosen float constants and ~12 named regexes**
are. Those constants were selected by hand against **14 binary fixtures**.
Parameters ≈ observations. There is no held-out set and no cross-validation.

14/14 is therefore not evidence of retrieval quality — it is evidence that a
25-parameter model can fit 14 points. ADR-0020's own item 4 ("pass/fail is
saturated again among leaders") is the symptom.

**Direction:** freeze the current 18 fixtures as a **dev** set. Author 30–40 new
fixtures as a **test** set from the corpus, never tuned against. Re-report every
strategy on both. Expect the gap between dev and test to be the real finding.

---

### R13: corpus-specific literals are baked into retrieval SQL and ranking

**Where:**

- `src/repair_assistant/retrieval/search.py:306-307` — `WHEN page = 44 THEN 1` and `WHEN text ~* 'TEST #1.*ACU Power Check' THEN 2` inside an `ORDER BY`.
- `src/repair_assistant/retrieval/rank.py:281` — demote `drum light`; `:289` — boost `TEST #1.*ACU Power Check`.
- `_DIAG_ENTRY_EVIDENCE` matches `Select any three \(3\) buttons`.
- `src/repair_assistant/qa/context.py` `_excerpt` — eight hardcoded needles (`"status led"`, `"shipping bolt"`, …).

These are eval-fixture answers written into the retriever. **A page number in an
`ORDER BY` is the single clearest signal in the repository that the gate is being
satisfied rather than passed.** None of it survives contact with a second
document set.

---

### R14: reranking was a charter-listed candidate and was never evaluated

`grep -rn "rerank" src/` returns **nothing**; the only hits are two ADR sentences
promising a future ADR. The charter lists reranking explicitly under
*Evidence-Driven Architecture*.

This is the conspicuous omission, because a cross-encoder reranker is **the
principled version of what the boost stack does by hand**. `bge-reranker-v2-m3`
is ~570 MB, CPU-runnable, MIT-licensed, and offline — it satisfies every charter
constraint including the zero-paid-infrastructure rule. You rejected BM25 with
genuine measurement; you never tested the technique that could delete 300 lines
of regex and make ranking brand-portable.

**Direction (`ADR-first`):** micro-bake `vector + applicability pre-filter +
cross-encoder rerank` against `vector_apply_boost`, **on the held-out set from
R12**. This is the highest-leverage missing experiment in the repository.

---

### R15: code and connector recall run unindexed regex scans

`code_fetch` and `connector_fetch` use `WHERE text ~* %s` over the whole `chunks`
table, on essentially every query, across four side-door retrievers. There is no
trigram GIN index and no `tsvector` column.

ADR-0020's decision not to adopt full-text **ranking** is well-argued; it left the
**recall** path on a sequential scan. Invisible at 20 documents; seconds per query
at 100k chunks.

---

### R16: changing the embedding model silently corrupts the index

**Where:** `embedding_model` is written in
`src/repair_assistant/ingest/store.py` (`set_embeddings`, and the column in
`001_init.sql`) and is **never read anywhere**:

```bash
grep -rn "embedding_model" src/ --include=*.py
```

returns only writes and the env-var accessor. `_embed_missing`
(`src/repair_assistant/ingest/pipeline.py:137`) fills **NULL** embeddings only.

Set `EMBEDDING_MODEL` to a different model and you get old-model vectors and
new-model queries in one HNSW index. No error, no warning — just quietly wrong
retrieval that no eval would attribute to the right cause.

**Direction:** assert at startup and at ingest that
`SELECT DISTINCT embedding_model FROM chunks WHERE embedding IS NOT NULL` matches
the configured model; fail loudly, and make `ingest --force` the documented
migration path. Roughly ten lines for a genuinely dangerous silent failure.

---

### R17: no relevance floor and weak context budget discipline

`format_evidence` ships the top-8 hits unconditionally up to 12k characters.
There is no minimum similarity threshold, so a query with no good match still
sends eight loosely related chunks and relies entirely on the LLM to abstain.
With `_diverse_top(max_per_doc=2)`, a question genuinely answered by one document
also receives six slots of noise. `_excerpt` truncation is driven by the
hardcoded needles noted in R13.

---

### R18: multi-turn retrieval has no query rewriting

`src/repair_assistant/diagnostic/graph.py` `_retrieval_query` concatenates the
last three user turns as a raw string. Coreference ("it does that too", "same
thing after I ran that") is unresolved. This is precisely the case where a cheap
LLM rewrite is standard practice, and it would let you retire several of the
acknowledgement heuristics in `qa/acks.py` and the symptom-anchor logic.

---

### R19: precedence depends entirely on hand-authored relationship edges

`corrects` / `supersedes` / `superseded_by` are hand-written in the manifest
YAML. If a new Technical Service Pointer arrives and nobody adds the edge, the
system confidently cites the **superseded** manual with a clean citation and full
confidence. There is no detection of "a newer publication references this one",
no document-age staleness signal, and no degraded confidence for
unknown-provenance documents.

Your headline capability — precedence over similarity — is a manual curation
artefact with a silent failure mode. This is the finding most likely to produce a
confidently wrong repair instruction in the field.

---

### R20: only two of your own six applicability axes are enforced

`docs/corpus/CORPUS_STUDY.md` (§ "Applicability is expressed on six independent
axes") states: *base model, engineering digit, platform, serial range,
effective-date window, software version* — "any one of them can exclude a
document that matches on all the others."

`src/repair_assistant/corpus/applicability.py` `document_applies` implements
**model pattern (with engineering digit) and serial range**. `platform`,
`regions`, `temporal.publication_date`, and software version are carried in the
manifest and never consulted. The charter also names "region where relevant" and
"publication/effective date".

Consequence today: a Canada-only document is citable for a US appliance, and a
bulletin with an effective-date window applies outside it. **The data is already
in the manifest; only the filter is missing.**

---

## 3. Agent prompt and generation

### R21: corpus-specific literals and brand are hardcoded in prompts

`src/repair_assistant/prompts/ask_system.txt` names publication numbers —
*"cite the installation instructions publication number (for example W11156977)"*,
*"(for example W11169652)"* — i.e. fixture answers, in the system prompt, on every
query. `diagnose_system.txt` is 40+ lines of negotiated behaviour, several rules
clearly scar tissue from individual failures ("Never ABSTAIN claiming no symptom
was specified when…"). Brand is hardcoded ("You are a Whirlpool…") in a
repository that markets itself as a reusable framework.

Same accretion dynamic as R48, in a second location.

---

### R22: the ABSTAIN override coerces the model past its own refusal

**Where:** `src/repair_assistant/diagnostic/graph.py:322` and the streaming twin
at `:485`:

> `"\n\nCRITICAL: The user confirmed prior checks passed. Do NOT abstain. Acknowledge briefly and give the next checklist category with [n] citations."`

This overrides the model's own judgement that the evidence does not support a
next step, **in a safety-relevant domain**, and pressures it to produce one
anyway. It doubles LLM cost on that turn, and the failure it invites — a
fabricated-but-cited next step — is exactly what the rest of the architecture
exists to prevent.

If the real defect is retrieval drift on acknowledgement turns (likely, see R18),
fix retrieval. Do not coerce the generator.

---

### R23: citation binding is recovered by regex, not guaranteed by structure

`src/repair_assistant/qa/context.py` `citations_from_answer` scrapes
`\[(\d+)\]` out of free text and maps indices to available citations. A model
that writes "per the service manual" instead of "[3]" produces an answer with
**zero** citations, and `citations_by_label_mention` then *guesses* the intended
source by substring-matching label themes.

**Direction:** structured output with an explicit schema
(`claims: [{text, evidence_index}]`) makes the claim→evidence binding verifiable
instead of inferred — and is the precondition for the groundedness check in R27.

---

### R24: no prompt versioning and no prompt evals

Prompts are `.txt` files. Their only test (`tests/test_prompts.py`) asserts that
certain substrings are present — a change-detector, not a quality gate. Nothing
measures whether a prompt edit improved or regressed behaviour except a manual
`bench-qa` run. Langfuse (already a dependency) provides prompt management with
versioning and eval linkage; it is unused.

---

### R25: generation call hygiene

- `temperature=0.2` (not `0`) for a determinism-critical, evaluated task.
- No `max_tokens` — unbounded output length and cost.
- No `seed`.
- `DEFAULT_LLM_MODEL = "gpt-4o-mini"` — a small model for safety-relevant reasoning, and an **alias** rather than a dated snapshot (see R37).
- The **full transcript** is re-sent every diagnose turn (`src/repair_assistant/diagnostic/prompts.py`, `_transcript`) with no summarisation or windowing: cost and context grow linearly and without bound per session.

---

## 4. Evaluation

> Overlaps with `docs/EVAL_FRAMEWORK_GAPS.md`. R26 restates its P0 with a
> stronger recommendation; R27–R30 are additional.

### R26 (Critical): no eval runs automatically

`.github/workflows/ci.yml` runs ruff, `pytest`, `repair-corpus validate`,
`repair-corpus status`, and the copyright guard. The project's own audit records
**E3 — "Wire `bench-safety` into CI — Skipped: all evals remain manual."**

For a project whose stated thesis is eval-driven development, every quality gate
depends on a human remembering to run a bench and read a scorecard. In a year the
scorecards will describe a system that no longer exists, and nothing will have
signalled the divergence. The safety bench explicitly needs neither OpenAI nor
Postgres; there is no technical reason it is not a required check. The retrieval
bench needs a database, which R38 provides.

**This is the finding that most determines whether the project's quality claims
remain true over time.**

---

### R27 (Critical): there is no groundedness or faithfulness metric

`grade_answer` (`src/repair_assistant/eval/grading.py`) checks **which** citations
appear. Nothing checks that the claim attached to `[3]` is supported by evidence
block 3. An answer that invents a procedure and appends a valid citation number
passes every deterministic rule in the repository.

The charter requires "citation correctness must itself be evaluated." What exists
is citation **identity**, not citation **correctness**.

The LLM judge cannot close the gap either:
`src/repair_assistant/eval/llm_judge.py` `build_judge_user_prompt` passes scenario
id, question, abstained flag, citations, answer, and criteria — and **never the
evidence text**. The judge is structurally incapable of assessing groundedness.

**Direction:** (a) pass evidence blocks to the judge; (b) add a claim-level
entailment check over `(claim, cited evidence block)` pairs — cheap and
largely deterministic once R23's structured output exists; (c) report an
unsupported-claim rate per scenario. Without this, "grounded" is a prompt
instruction, not a measured property.

---

### R28: citation matching is bidirectional substring matching

`matches_citation` in `src/repair_assistant/eval/grading.py` passes on
`needle == k or k.startswith(needle) or needle in k or needle_l in k.lower()`. So
`must_cite: W11169652` is satisfied by `W11169652 Rev B` **or** `W11169652 Rev D`
— meaning your revision-precedence assertions cannot actually distinguish
revisions, which is the exact capability those fixtures exist to prove.

---

### R29: missing metrics against the charter's own list

`src/repair_assistant/retrieval/bench.py` computes `hit_at_k`, `recall_at_k`,
`precision_at_k` — **all rank-insensitive**. A change that keeps the right
document in the top-8 but moves it from rank 1 to rank 8 (materially degrading the
answer, given the 12k-character evidence budget) scores identically. The charter
lists **MRR** and **nDCG**.

Also absent everywhere: latency, token usage, cost, failure rate — all four named
in the charter's *System* evaluation dimension. Langfuse `generation` spans record
no usage (see R43).

---

### R30: LLM judge design issues

Single judge; **same model family as the generator** (`llm_model()` for both), so
self-preference bias is unmitigated; binary verdict with no confidence or
abstention; no order/position controls; human agreement established only against a
10-case calibration pack (`evals/qa/judge-calibration.yaml`). The charter's
*Evaluator Philosophy* says "do not assume an LLM judge is objective simply
because it produces a numerical score" — the calibration pack is the right
instinct, at roughly a tenth of the size needed to detect drift.

---

## 5. Diagnostic workflow

### R31: the diagnostic workflow has no structured state

`src/repair_assistant/diagnostic/state.py` `DiagnosticGraphState` carries
`messages` plus this turn's evidence and safety fields. There is no `hypotheses`,
no `ruled_out`, no `observations`, no step counter.

The charter asked for explicit, inspectable workflow state: *identify appliance →
understand symptoms → obtain missing information → retrieve → determine causes →
select next step → incorporate result → refine → recommend / escalate*. What
exists is chat history plus a symptom-anchor heuristic. "Which checks are already
cleared" is re-derived by the LLM re-reading the transcript every turn — which is
precisely why `diagnose_system.txt` needs four separate rules about not
mis-claiming things were ruled out.

**Consequences:** cannot produce a repair summary; cannot resume or hand off to a
technician; cannot evaluate **trajectory correctness** (which is why gap #7 in the
project's own audit stays "thin"); and roughly half the diagnose prompt exists to
compensate.

---

### R32: sessions are in-memory, capped at 32, and LRU-evicted

`src/repair_assistant/api/sessions.py:16` (`DEFAULT_SESSION_MAX = 32`),
`_evict_oldest_locked`. The 33rd concurrent session silently evicts the
least-recently-used one — an active user mid-diagnosis gets a `410` and loses
their state. No persistence across restarts (documented), no horizontal scaling
(process-local state). **Postgres is already a hard dependency**; sessions belong
there, which also unblocks R42's history feature.

---

## 6. Content coverage

### R33: the system cannot see figures or wiring diagrams, and does not say so

```bash
grep -rn "image\|figure\|diagram\|ocr" src/repair_assistant/parsing/
```

returns **nothing**. ADR-0024 defers PaddleOCR as "hooks documented, not
implemented."

Why this is more than a to-do, from your **own** corpus study
(`docs/corpus/CORPUS_STUDY.md`):

- It records that the tech sheet devotes pages 26–27 to **wiring diagrams**.
- It records that control-panel artwork extracts as `h o ld`, `C y c le`, and isolated characters — "meaningless tokens in any index" — and those chunks are nonetheless **ingested and embedded** with no quality floor, adding pure noise to the ANN index.
- It records precedence rule #3: *"Product-supplied wiring diagram overrides the manual's own (stated in the manual, which calls its diagram 'typical' and 'for training only')."* You identified a precedence rule operating entirely over content the pipeline cannot read.

For the **technician** audience — the one permitted procedural depth — wiring
diagrams, connector locations, and exploded parts views are arguably the highest
value content in a service manual. "Check continuity at J36" is close to useless
without the diagram showing where J36 is.

The system does not know it cannot see the diagram, so it never says so.

**Direction (cheap, high value, no OCR required):** classify figure/diagram pages
during parsing, exclude their garbage text from the index, and surface an honest
note when retrieved evidence cross-references a figure: *"this procedure
references Figure 2 on page 26, which this assistant cannot read — consult the
source document."* That converts a silent failure into an honest one in about a
day. Full OCR / layout extraction is a separate `ADR-first` decision.

---

### R34: Spanish and French content is ingested and unusable

Manifests declare `languages: [en-US, fr-CA, es-US]`;
`src/repair_assistant/parsing/language.py` detects them with a six-marker
heuristic per language; non-English chunks are ingested and then demoted in
`reference_fetch`'s `ORDER BY`. Prompts and UI are English-only.

So Spanish-language content is **index weight with no product value**, while
Spanish-speaking appliance owners — a meaningful segment of the US market for this
product category — are excluded from a product that already holds the Spanish
source text. `product-decision` on whether to serve them; the current state (carry
the cost, capture none of the value) is the worst of both.

---

## 7. Scale, resilience, reproducibility

### R35: a pooled DB connection is held for the entire LLM generation

`src/repair_assistant/api/db_pool.py:12` — `DEFAULT_POOL_SIZE = 4`. The stream
routes declare `db: Database = Depends(get_db)`. FastAPI holds a generator
dependency open until the response **completes**; for a `StreamingResponse` that
is after the last token.

So each in-flight request pins a database connection for the full 10–30 s of
OpenAI generation, during which **zero** database work happens. Effective
concurrency is 4; the fifth caller waits up to
`REPAIR_DB_POOL_TIMEOUT_SECONDS` (30 s) and then fails.

Compounding: the BGE embedder is a process-wide singleton doing CPU inference with
no queue or batching, so concurrent `encode` calls contend.

Correct for a single-user LAN laptop; wrong relative to the "production quality"
framing. **Direction:** acquire the connection for retrieval and release it before
generation — never hold a pooled resource across a third-party network call.

---

### R36 (Critical): no retry, unhandled LLM error classes, and no degraded mode

- **No retry or backoff anywhere.** `grep -rn "retry\|backoff\|tenacity\|max_retries" src/` finds only the R22 abstain-coercion and a parser layout retry. A single transient 429 or 500 becomes a user-facing failure.
- **Unhandled error class.** `ask_route` / `diagnose_route` catch `LLMTimeoutError` and `RuntimeError`. `openai.RateLimitError` / `APIStatusError` inherit from neither → uncaught → HTTP 500. **[inferred — reproduce by injecting the exception before fixing.]**
- **Error detail echoed to the client.** The stream routes' bare `except Exception` yields `str(exc)` straight into the SSE stream.
- **No degraded mode.** When generation fails you have *already successfully retrieved applicable, cited evidence*. Returning that ("we couldn't compose an answer; here are the three applicable passages with citations") is strictly better than an error and nearly free — `SearchResponse` already exists.
- No circuit breaker and no spend ceiling (see R7).

---

### R37: no dependency lockfile — the ADR evidence cannot be reproduced

`pyproject.toml` pins ranges only: `sentence-transformers>=3.0,<5`,
`langgraph>=0.2,<2`, `openai>=1.40,<3`, `pdfplumber>=0.11,<0.12`. There is no
lockfile, no hash pinning, no recorded resolved environment.

The charter names **reproducibility** as a production-quality concern, and the
entire ADR evidence base consists of scorecards produced by running these
libraries. `pip install -e .` today and in six months resolves different
`sentence-transformers` and possibly a different torch, which changes embeddings,
which changes retrieval, which changes every number in ADR-0011 / 0020 / 0024 —
with no way to regenerate the original.

**The ADRs currently record decisions whose evidence cannot be reproduced.**

Same class of problem: `LLM_MODEL` defaults to `gpt-4o-mini`, an **alias** that
the provider silently repoints. Every Q&A scorecard is against an unversioned
model.

**Direction:** a lockfile (`uv.lock` or hash-pinned requirements), a dated model
snapshot, and both stamped into each scorecard header. Roughly half a day, and it
converts the ADR corpus from assertions into evidence.

---

### R38: 270 tests, and none touch Postgres

```bash
grep -rln "psycopg\|Database(" tests/    # → no matches
grep -rc "def test_" tests/*.py           # → 270 tests
```

All 270 tests use fakes and monkeypatching. That means the most intricate and
business-critical code in the repository — the five hand-written SQL queries in
`src/repair_assistant/retrieval/search.py`, including regex `ORDER BY` clauses,
`text[]` overlap operators, `ANY(%s::int[])` casts, and the HNSW-backed vector
fetch — **is never executed in CI**. A broken neighbour join in `connector_fetch`,
or a pgvector version bump that changes operator behaviour, ships green and is
discovered only when a human manually runs a bench.

pgvector runs as a GitHub Actions service container in ~10 lines of YAML. With a
small seeded fixture corpus this closes the largest blind spot in the test suite —
and it is the prerequisite that unblocks putting `bench-retrieve` in CI (R26).

---

### R39: build context leaks copyrighted PDFs and secrets over plaintext TCP

- There is **no `.dockerignore`** (`ls -a docker/` and repo root confirm).
- `docker/compose.yaml` uses `build.context: ..` (repo root) and its header documents `set DOCKER_HOST=tcp://DOCKER_HOST:2375`.

Therefore the documented build workflow transmits `corpus/documents/*.pdf` (the
copyrighted manuals) and `.env.local` (Postgres password + OpenAI key) **over
unencrypted TCP to the LAN host on every build**. The `Dockerfile` only `COPY`s
selected paths, so they do not land in the *image* — but they do leave the
machine.

The CI copyright guard is a genuinely good control, and it protects **git only**.
This is the same class of leak through a different door.

Also: the container runs as **root**, and `sentence-transformers` downloads BGE
from HuggingFace on first use with no `HF_HOME`, no pre-baked model, and no
`local_files_only` — so a fresh container without internet cannot serve a request,
which softens the "cloud-independent / runnable locally" claim.

---

### R40: the manifest is re-parsed from disk on every request

`_manifest()` in `src/repair_assistant/api/app.py` calls `manifest_mod.load()`
with no caching; `load()` globs and `yaml.safe_load`s every file.
`corpus_supports_appliance` then iterates every document. Trivial today;
O(corpus) per request permanently. Needs a cache with an explicit invalidation
story (mtime or an explicit reload endpoint), not just an `lru_cache`.

---

## 8. Product and business

### R41 (Critical, product): there is no user feedback signal anywhere in the product

- No thumbs up/down, no rating, no "did this solve it?", no comment box in `src/repair_assistant/api/static/index.html`.
- No `langfuse.score()` call anywhere in `src/repair_assistant/observability/`.
- `src/repair_assistant/eval/mine_traces.py` `classify_trace` detects exactly **six** hand-written failure regexes, all door-lock / F5E2 / diagnostic-entry specific.

So `mine_traces` is a **regression detector wearing the clothes of a discovery
mechanism**: a novel production failure produces a trace it returns `[]` for, and
it is never surfaced. Combined with the absence of feedback, the entire quality
signal for a deployed system is *a regex over the assistant's own text*.

You cannot answer "is this working for users?" — not approximately, not
directionally.

**Direction:** two buttons writing a Langfuse score, then mine **low-scored**
traces rather than pattern-matched ones. That converts the loop from
closed-on-known-failures to open-to-unknown-ones. Cheap, and it is the
precondition for every product decision below.

---

### R42: the user journey has no outcome

The journey ends at "here is a cited checklist." There is no completion state, no
resolution capture, no follow-up.

The two things that make an appliance repair assistant commercially real —
**deflecting a service call** or **converting to a part order / service booking** —
are both unmeasured and unbuilt, despite the corpus containing a parts list
(`parts-list-w11320547`) and a warranty document. When the assistant concludes
"the door lock assembly has failed," nothing links that to the part number in the
parts list it has already indexed.

Related: no accounts, no saved appliances, no history. A user re-enters model and
serial every session, and a diagnosis is lost on restart (R32). Repair is
inherently multi-session — "I ordered the part, it arrived, now what?" is a normal
journey the product cannot support.

`product-decision`. Recorded because a technically excellent RAG pipeline with no
outcome capture is a demo with good engineering, which is precisely the framing
the charter rejects.

---

### R43: no cost model

Langfuse `generation` spans in
`src/repair_assistant/observability/langfuse_tracing.py` record model and
input/output but **no token usage**. So cost per answer, cost per session, and the
cost delta of the R22 double-LLM retry are all unknown. The product cannot be
priced and no budget alert can be set.

---

### R44: no data governance for traces

Serial numbers, symptoms, and free-text questions are sent to Langfuse with no
redaction, no retention policy, and no documented deletion path. Self-hosting
answers the vendor question but not "what do we keep, for how long, and how does
someone get it deleted." Serial numbers are device-identifying and, combined with
free text, edge toward personal data in several jurisdictions.

---

## 9. Documentation and hygiene

### R45: ADR-0014 overclaims CI enforcement

`docs/adr/0014-safety-policy.md` closes with "deterministic action classification
is enforced in CI today," while `docs/EVAL_FRAMEWORK_GAPS.md` records **E3
skipped — all evals remain manual**. The claim is *approximately* true via
hand-duplicated unit tests (R46), but the fixture suite itself does not run. Worth
a one-line correction — the ADR corpus's value depends on its claims being
literally checkable.

### R46: safety fixtures are duplicated by hand in unit tests

`tests/test_safety_policy.py` re-states ~13 of the 15 cases in
`evals/safety/fixtures.yaml` as Python. Two copies of the same truth will drift.
Parameterising the unit test over the YAML file makes the fixture the single
source and gets the suite into CI for free (partially addressing R26).

### R47: manifest curation is a content-ops program with no tooling

`corpus/manifest/tsp-w11375982.yaml` is ~100 lines of hand-authored YAML: 23 model
patterns, serial ranges, cross-document `corrects` edges, and prose reasoning
about authenticity. **The quality is genuinely excellent** — and entirely manual.

At 20 documents this is a differentiator. At 2,000 it is a headcount request with
no cost model, no LLM-assisted bootstrap-with-human-review path, and no drift
detection between a manifest entry and the document it describes. This is the
distance between "proven on a reference corpus" and "a product."

### R48: every new failure adds a rule, and rules never retire

Count the accretion: 4 side-door retrievers, ~25 boost constants, ~12 named
regexes in `rank.py`, ~10 in `query_expand.py`, 8 hardcoded excerpt needles, 6
corpus-specific lines in `ask_system.txt`, 6 failure regexes in `mine_traces.py`.

ADR-0020 names the pattern exactly — *"That is hybrid retrieval built one regex at
a time"* — and then the amendment adds two more ranking rules. Maintenance cost is
superlinear because the rules **interact**: see the nested `installation` /
`technician` / `knowledge_article` conditionals in the error-code boost block of
`filter_and_rank`. A second brand does not add rules; it multiplies the
interaction surface.

**This is the finding that most determines whether the codebase is still tractable
in a year.** R14 (reranking) is the concrete path out.

---

## Appendix A — what is genuinely strong

Recorded so that remediation does not damage it:

- **ADR discipline.** Decisions carry problem, alternatives, evidence, and consequences. ADR-0020 in particular corrects an earlier ADR's reasoning rather than quietly superseding it — that is rare and valuable.
- **The corpus study.** `docs/corpus/CORPUS_STUDY.md` is the strongest document in the repository: it derived the chunking requirements from observed extraction failures, caught the F6E1-code-severed-from-remedy problem empirically, and even recorded a manufacturer typo as a constraint on exact-match tests.
- **Manifest provenance.** Distinguishing canonical hash from instance hashes, recording `url_status`, `access_method`, and honest reasoning about authenticity ("authenticity rests on internal evidence: three pages in en/fr/es…") is better than most commercial document pipelines.
- **The applicability and precedence concept.** Modelling relevance separately from authority and applicability is the correct core insight for this domain, and the serial year-code decoder is careful work.
- **The copyright guard.** A CI job, not a README warning. The comment in `.github/workflows/ci.yml` says exactly the right thing.
- **Deterministic-grader-first, judge-opt-in.** The right default, and the charter's evaluator philosophy is correct.
- **The project's own gap audit.** `docs/EVAL_FRAMEWORK_GAPS.md` is honest about false coverage and about skipping E3. Several findings here were already known there; the additions are noted as such.

---

## Appendix B — reproduce the evidence

Verifiable, read-only checks behind the strongest claims:

```bash
# R14 — reranking never implemented
grep -rn "rerank\|CrossEncoder" src/

# R16 — embedding_model written, never read
grep -rn "embedding_model" src/ --include=*.py

# R33 — no figure / image / OCR path
grep -rn "image\|figure\|diagram\|ocr" src/repair_assistant/parsing/

# R36 — no retry or backoff
grep -rn "retry\|backoff\|tenacity\|max_retries" src/ --include=*.py

# R38 — no test touches a database
grep -rln "psycopg\|Database(" tests/

# R41 — no feedback capture, no Langfuse scores
grep -rn "thumb\|feedback\|rating\|helpful" src/repair_assistant/api/static/index.html
grep -rn "score" src/repair_assistant/observability/

# R13 — corpus literals in retrieval SQL
grep -n "page = 44\|ACU Power Check\|drum light" \
  src/repair_assistant/retrieval/search.py src/repair_assistant/retrieval/rank.py

# R8 — prompt injection never considered
grep -rn "injection" docs/ src/
```

---

## Appendix C — suggested sequencing

Each row is a candidate branch. `ADR-first` items need a written decision before
code.

| Order | Findings | Why this order |
| --- | --- | --- |
| 1 | R1, R36, R10 | User-facing risk. None requires an architectural decision. |
| 2 | R16, R5, R39 | Silent-corruption and exposure defects; small, isolated diffs. |
| 3 | R38, R46 | Database in CI, plus a fixture-driven safety suite. Unblocks step 4. |
| 4 | R26, R37 | Evals become gates; scorecards become reproducible. |
| 5 | R41 | Feedback capture — the precondition for knowing anything else worked. |
| 6 | R27, R23 | Structured output, then groundedness measurement on top of it. |
| 7 | R12, R14 (`ADR-first`) | Held-out fixture split, then the reranker bake-off. |
| 8 | R11, R20 (`ADR-first`) | Applicability as a pre-filter, with the remaining four axes. |
| 9 | R31, R32, R35 | Structured diagnostic state, durable sessions, connection lifetime. |
| 10 | R33, R47, R42 (`product-decision`) | Coverage honesty, curation tooling, journey outcome. |

**Do not start at step 7 or 8.** Those are the intellectually interesting ones and
the most likely to be made worse without steps 3–4 in place first: without evals
in CI and a reproducible environment, a retrieval change cannot be shown to be an
improvement.
