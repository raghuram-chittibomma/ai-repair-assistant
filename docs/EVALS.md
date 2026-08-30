# Evaluation runbook (manual)

Eval harnesses exist at every pipeline layer. **All eval benches are run by
hand** — not in CI and not on a schedule. Unit tests cover graders and ranking
without OpenAI or Postgres.

Framework gaps and prioritized backlog:
[EVAL_FRAMEWORK_GAPS.md](EVAL_FRAMEWORK_GAPS.md).

Use `python -m repair_assistant.corpus.cli …` on Windows if `repair-corpus` is
not on PATH.

---

## Levels

| Level | Command | Needs | Fixtures | Output |
| --- | --- | --- | --- | --- |
| Unit / grader | `pytest` | none | `tests/` | pass/fail |
| Parsing | `bench-parse --write` | local PDFs for fixtures | `evals/parsing/fixtures.yaml` | `evals/parsing/results/scorecard.md` |
| Chain smoke | `bench-chain --write` | DB + embedder (+ OpenAI unless `--skip-ask`) | `evals/chain/fixtures.yaml` | `evals/chain/results/scorecard.md` |
| Retrieval | `bench-retrieve --write` | live Postgres + embeddings | `evals/retrieval/fixtures.yaml` | `evals/retrieval/results/scorecard.md` (pass/fail + Hit@K / Recall@K / Precision@K / MRR / nDCG@K / latency) |
| Safety | `bench-safety` | none | `evals/safety/fixtures.yaml` (CI gate) + `evals/safety/adversarial.yaml` (R4 rates, not a gate) | stdout + CI gate |
| Q&A smoke | `bench-qa --write` | DB + `OPENAI_API_KEY` | `evals/qa/smoke-scenarios.yaml` | `evals/qa/results/scorecard.md` + JSON under `runs/` |
| Candidates | `bench-candidates --write` | DB + `OPENAI_API_KEY` | `evals/scenarios/candidates.yaml` + `evals/qa/candidates-grading.yaml` | `evals/qa/results/candidates-scorecard.md` + JSON under `runs/` |
| Promote failure | `promote-eval --run … --scenario ID` | prior run JSON | — | YAML draft (optional `--write` into grading overlay) |
| Mine Langfuse traces | `mine-traces --since 7d [--write]` | Langfuse + DB + OpenAI (replay) | live traces | `evals/qa/drafts/mine-report-*.md` analysis only (ADR-0023) |
| Judge calibrate | `bench-judge-calibrate --write` | `OPENAI_API_KEY` (no DB) | `evals/qa/judge-calibration.yaml` | `evals/qa/results/judge-calibration-scorecard.md` |
| Prune run logs | `prune-eval-runs --keep N` | none | `evals/qa/results/runs/` | dry-run list (use `--execute` to delete) |

Hard corpus scenarios live in `evals/scenarios/candidates.yaml` (`status: ready`).
Deterministic overlays for the candidate bench are in
`evals/qa/candidates-grading.yaml`. Every `ready` scenario must have ≥1
machine-checkable rule after merge (unit-tested). Overlay entries may set
`requires_judge: true` when prose `fails_if` / `expect` still matter — pass
`--judge` to grade those after the deterministic gate (ADR-0019). Diagnose
scenarios use `command: diagnose`, `turns:`, and optional `turn_grades:` (per-turn
det keys); without `turn_grades`, top-level keys apply to `expect_turn` (or the
last turn). All eval benches stay **manual** (not CI-scheduled).

---

## Full manual pass (recommended order)

Cheap / offline first, then live OpenAI:

```powershell
pytest -q

python -m repair_assistant.corpus.cli bench-parse --write
python -m repair_assistant.corpus.cli bench-safety

# Needs LAN Postgres (DATABASE_URL in .env.local)
# First run of vector_apply_rerank (ADR-0027) downloads CrossEncoder weights.
python -m repair_assistant.corpus.cli bench-retrieve --write

# Cross-layer: re-parse/ingest one doc → production search → ask
python -m repair_assistant.corpus.cli bench-chain --write

# Needs OpenAI as well
python -m repair_assistant.corpus.cli bench-qa --write
python -m repair_assistant.corpus.cli bench-candidates --write

# Optional: also LLM-judge prose expect/fails_if (extra OpenAI cost)
python -m repair_assistant.corpus.cli bench-candidates --write --judge

# Judge calibration (frozen answers; no DB)
python -m repair_assistant.corpus.cli bench-judge-calibrate --write

# Prune old run JSON (dry-run by default)
python -m repair_assistant.corpus.cli prune-eval-runs --keep 5
```

Optional: re-run a single scenario

```powershell
python -m repair_assistant.corpus.cli bench-qa --write --scenario acu-led-step-10
python -m repair_assistant.corpus.cli bench-candidates --write --scenario installation-fault-not-component-fault
```

### Promote a failure into a grading draft

After a failed `--write` run, draft an overlay stub for review (does **not**
become a live gate until you move keys out of `.draft`):

```powershell
python -m repair_assistant.corpus.cli promote-eval `
  --run evals/qa/results/runs/candidates-YYYYMMDDTHHMMSSZ.json `
  --scenario some-failed-id

# optional: nest under candidates-grading.yaml → scenarios.<id>.draft
python -m repair_assistant.corpus.cli promote-eval `
  --run evals/qa/results/runs/candidates-YYYYMMDDTHHMMSSZ.json `
  --scenario some-failed-id --write
```

---

## Interpreting results

- Exit code **0** = all graded cases passed (safety: all hard fixtures).
- Exit code **non-zero** = one or more failures; read the printed scorecard.
- `--write` refreshes the markdown scorecard and (for Q&A / candidates) a
  timestamped JSON run log with answers, citations, latency, and pass/fail.
  Ask/diagnose bind citations from structured `claims` ([ADR-0028](adr/0028-structured-claim-evidence.md)).
  Groundedness (R27 / [ADR-0029](adr/0029-claim-groundedness.md)): unsupported-claim
  rate plus a hard fail on zero-overlap invented claims.
  Prompt edits are still a manual `bench-qa` gate ([ADR-0030](adr/0030-prompt-version-stamps.md)).
- Commit scorecards when you want a durable baseline; intermediate run JSONs
  are optional.

### Retrieval IR metrics (diagnostic)

`bench-retrieve` still gates on pass/fail (`must_cite` / `must_not_cite`). The
scorecard also reports:

| Metric | Meaning |
| --- | --- |
| **Hit@K** | All `must_cite` labels present (and `must_cite_any` satisfied) in top‑K |
| **Recall@K** | Fraction of required targets found (`must_cite` each count; `must_cite_any` is one group) |
| **Precision@K** | Fraction of unique retrieved docs that match a relevant label |
| **MRR** | Reciprocal rank of the first relevant hit (0 if none in top‑K) |
| **nDCG@K** | Binary nDCG over the same targets as Recall@K |
| **Forbidden@K** | Count of `must_not_cite` labels that appeared in top‑K |
| **Latency** | Wall time of `run_strategy` per fixture; scorecard reports mean / p50 / p95 |

Optional fixture field `relevant:` overrides the relevant label set for IR
math. Fixtures with only `must_not_cite` leave Hit/Recall/Precision as `n/a`.

**Release gate** = pass/fail. Use IR numbers to compare strategies and spot
noise or missed docs — not as a substitute for hard corpus cases. On the
current 18-fixture decision set, `vector_apply_boost` is the measured baseline
(tied with `union_literal_apply` on MRR/nDCG, faster). See [ADR-0020](adr/0020-hybrid-retrieval-retest.md).
`vector_apply_rerank` is an ADR-0027 bake-off control (cross-encoder, no
boosts). Measured and rejected: 10/14 hard, MRR 0.57 vs baseline 0.83. Not
the production path.

### Retrieval fixture families

18 fixtures, **14 hard** (see current `evals/retrieval/results/scorecard.md` and
[ADR-0020](adr/0020-hybrid-retrieval-retest.md)). Ground truth for rare-literal
and product-class additions was verified against ingested chunks / manifest
applicability — a fixture that asserts a document holds a token it does not hold
measures nothing.

| Family | Tests |
| --- | --- |
| `applicability-serial-range` | Serial-range decisions, in and out of scope |
| `applicability-product-category` | Front-load vs top-load vs laundry tower |
| `applicability-engineering-digit` | Exact-model parts list must not match adjacent base |
| `applicability-multi-brand` | Maytag MHW* covered by shared platform manual |
| `precedence-bulletin-over-manual` | Correcting bulletin outranks the manual |
| `precedence-revision` / supersession | Rev B preference; synthetic new-pub supersession |
| `near-duplicate-tech-sheets` | Pub-ID identity when page text is twin |
| `authority-depth` | Technician question prefers tech sheet over consumer KB |
| `retrieval-bibliographic` | “What is W…” publication lookup |
| `retrieval-exact-identifier` | Error codes, connectors, part numbers |
| `retrieval-term-mismatch` | Query term absent from target (“shipping” vs “transport”) |

Rare literals vs term mismatch remain a deliberate pair. Leaders currently
saturate **14/14** hard on pass/fail — compare mean Precision@K. Bake-off cores
(`run_strategy`) omit production side doors unless the `production_search`
strategy is included; see [EVAL_FRAMEWORK_GAPS.md](EVAL_FRAMEWORK_GAPS.md).

### IR ↔ candidates crosswalk (same stories, different IDs)

| Product story | IR fixture | Candidates scenario | Notes |
| --- | --- | --- | --- |
| ACU LED bulletin | `acu-led-step-10` | `acu-led-step-10` | Aligned |
| Wrong-platform door lock | `door-locks-wont-run-wrong-platform` | `door-locks-wont-run-wrong-platform` | Smoke uses `…-no-wrong-bulletin` |
| F5E2 category | `f5e2-front-load-not-top-load` (hard KB cite) | `f5e2-three-way` (`expect_cites_any` + wrong-KB ban) | IR owns three-way KB; Q&A accepts manual/hub |
| Serial in/out | soft `serial-*-door-lock-tsp` | `serial-outside-range` ready; `serial-inside-range` **deferred** (E4) | Align hardness with IR soft inside-range |
| Rev B manual | `manual-rev-b-acu-led` | `known-gap-revised-manual` | Different asserts |
| Near-dup page 1 | `tech-sheet-page1-by-pub` | `identifier-only-distinction` | Aligned intent |
| Supersession | `synth-owners-manual-supersession` | `superseded-owners-manual` | IR synthetic; Q&A `needs_document` |
| Tech depth F5E2 | `f5e2-tech-sheet-not-kb` | `f5e2-technician-depth` | Aligned intent |

### Synthetic eval documents

When a product-class IR case is blocked on a missing OEM PDF (e.g. current
owner's manual supersession), the bake-off may use **synthetic** docs under
`evals/retrieval/synthetic/`:

- `doc_id` always starts with `synth-`; publication numbers with `SYNTH-`
- Never stored under `corpus/documents/` or `corpus/manifest/`
- Upserted only by `bench-retrieve`; production `search()` drops them
- Fixtures that use them set `source: synthetic`

Do not treat synthetic pubs as real literature in docs or demos.

### Live traces (optional Langfuse)

Self-hosted Langfuse can record `ask` / `diagnose` runs for inspection
([LANGFUSE.md](LANGFUSE.md), ADR-0018). Benches do **not** require Langfuse;
leave `LANGFUSE_*` keys empty to disable tracing. Offline mine of traces into
a **reviewable analysis report** (with replay so fixed bugs stay closed) is
`mine-traces` ([ADR-0023](adr/0023-trace-driven-eval-mining.md)):

```powershell
python -m repair_assistant.corpus.cli mine-traces --since 7d --write
```

`--write` only creates `evals/qa/drafts/mine-report-*.md`. It does not edit
live fixtures or write draft YAML / mine-state. Copy suggested stubs from the
report by hand if you want new smoke/candidates.

### Recent baselines (hand-run)

| Bench | Result | Notes |
| --- | --- | --- |
| Safety | 15/15 | Deterministic; required CI check (`bench-safety`) |
| Retrieval | 14/14 hard (`vector_apply_boost`) | Includes `production_search` strategy |
| Chain smoke | — | `bench-chain` harness ready; E12 deferred (no boundary failure to bake) |
| Q&A smoke | 5/5 | Live |
| Candidates | ready gate (post-E4) | `f5e2-three-way` cite relaxed; `serial-inside-range` deferred |

Added (2026-08-27, not yet hand-baselined): smoke + candidates
`mid-cycle-stop-diag-entry`, `door-got-locked-unlock`,
`door-lock-underspecified-clarify`. Run:

```powershell
python -m repair_assistant.corpus.cli bench-qa --write --scenario mid-cycle-stop-diag-entry
python -m repair_assistant.corpus.cli bench-candidates --write --scenario mid-cycle-stop-diag-entry
```

Gap analysis: [EVAL_FRAMEWORK_GAPS.md](EVAL_FRAMEWORK_GAPS.md).

---

## Out of scope (for now)

- CI benches that need OpenAI or the real corpus (`bench-qa`, `bench-retrieve`,
  `--judge`) — operators run those by hand. Offline `bench-safety` is a
  required CI check. SQL correctness tests (`tests/test_postgres_sql.py`) run
  against a disposable `pgvector` service in CI via `REPAIR_TEST_DATABASE_URL`;
  they never use the LAN `DATABASE_URL`.
- Auto-merging promoted drafts into live overlay keys (always human review)
- Auto-merging `mine-traces` report suggestions into `status: ready` (ADR-0023)

See ADR-0015, ADR-0017, and ADR-0019 for Q&A benches, candidates, and judge/promote.
