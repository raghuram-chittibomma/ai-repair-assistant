# Evaluation runbook (manual)

Eval harnesses exist at every pipeline layer. **Live benches are run by hand** —
not in CI and not on a schedule. Unit tests cover graders and ranking without
OpenAI or Postgres.

Use `python -m repair_assistant.corpus.cli …` on Windows if `repair-corpus` is
not on PATH.

---

## Levels

| Level | Command | Needs | Fixtures | Output |
| --- | --- | --- | --- | --- |
| Unit / grader | `pytest` | none | `tests/` | pass/fail |
| Parsing | `bench-parse --write` | local PDFs for fixtures | `evals/parsing/fixtures.yaml` | `evals/parsing/results/scorecard.md` |
| Retrieval | `bench-retrieve --write` | live Postgres + embeddings | `evals/retrieval/fixtures.yaml` | `evals/retrieval/results/scorecard.md` (pass/fail + Hit@K / Recall@K / Precision@K) |
| Safety | `bench-safety` | none | `evals/safety/fixtures.yaml` | stdout scorecard |
| Q&A smoke | `bench-qa --write` | DB + `OPENAI_API_KEY` | `evals/qa/smoke-scenarios.yaml` | `evals/qa/results/scorecard.md` + JSON under `runs/` |
| Candidates | `bench-candidates --write` | DB + `OPENAI_API_KEY` | `evals/scenarios/candidates.yaml` + `evals/qa/candidates-grading.yaml` | `evals/qa/results/candidates-scorecard.md` + JSON under `runs/` |
| Promote failure | `promote-eval --run … --scenario ID` | prior run JSON | — | YAML draft (optional `--write` into grading overlay) |

Hard corpus scenarios live in `evals/scenarios/candidates.yaml` (`status: ready`).
Deterministic overlays for the candidate bench are in
`evals/qa/candidates-grading.yaml`. Prose `fails_if` / `expect` fields are still
authoritative for humans; pass `--judge` to have an LLM grade them after the
deterministic gate (ADR-0019).

---

## Full manual pass (recommended order)

Cheap / offline first, then live OpenAI:

```powershell
pytest -q

python -m repair_assistant.corpus.cli bench-parse --write
python -m repair_assistant.corpus.cli bench-safety

# Needs LAN Postgres (DATABASE_URL in .env.local)
python -m repair_assistant.corpus.cli bench-retrieve --write

# Needs OpenAI as well
python -m repair_assistant.corpus.cli bench-qa --write
python -m repair_assistant.corpus.cli bench-candidates --write

# Optional: also LLM-judge prose expect/fails_if (extra OpenAI cost)
python -m repair_assistant.corpus.cli bench-candidates --write --judge
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
| **Forbidden@K** | Count of `must_not_cite` labels that appeared in top‑K |

Optional fixture field `relevant:` overrides the relevant label set for IR
math. Fixtures with only `must_not_cite` leave Hit/Recall/Precision as `n/a`.

**Release gate** = pass/fail. Use IR numbers to compare strategies and spot
noise or missed docs — not as a substitute for hard corpus cases.

### Retrieval fixture families

12 fixtures, 9 hard. Ground truth for the rare-literal family was verified by
probing the ingested `chunks` table for each literal, not inferred from the
manifest — a fixture that asserts a document holds a token it does not hold
measures nothing.

| Family | Tests |
| --- | --- |
| `applicability-serial-range` | Serial-range decisions, in and out of scope |
| `applicability-product-category` | Front-load vs top-load vs laundry tower |
| `precedence-bulletin-over-manual` | Correcting bulletin outranks the manual |
| `retrieval-exact-identifier` | Rare literals: error codes, connector IDs, part numbers, procedure labels |
| `retrieval-term-mismatch` | Query term absent from the target document ("shipping" vs "transport" bolts) |

The last two families are a deliberate pair. Rare literals reward an exact-match
arm; term mismatch punishes one. A strategy that wins the first family by losing
the second has not improved, and the scorecard should make that visible rather
than average it away.

Four strategies currently saturate the gate at 9/9 (`vector_apply_boost`,
`hybrid_rrf_apply`, `union_literal_apply`, `union_lexical_apply`), so pass/fail
no longer separates the leaders — compare mean Precision@K, and see
[ADR-0020](adr/0020-hybrid-retrieval-retest.md) for why a full-text arm is not
adopted. Note that `bench-retrieve` measures retrieval cores only:
`run_strategy` omits the `connector_fetch` / `reference_fetch` /
`manual_rev_fetch` recalls that `search()` uses in production.

### Live traces (optional Langfuse)

Self-hosted Langfuse can record `ask` / `diagnose` runs for inspection
([LANGFUSE.md](LANGFUSE.md), ADR-0018). Benches do **not** require Langfuse;
leave `LANGFUSE_*` keys empty to disable tracing.

### Recent baselines (hand-run)

| Bench | Result | Notes |
| --- | --- | --- |
| Safety | 10/10 | Deterministic |
| Q&A smoke | 5/5 | Live |
| Candidates | 22/24 | Deferred: `f5e2-three-way`, `serial-inside-range` |

---

## Out of scope (for now)

- CI / scheduled live benches (OpenAI cost and LAN DB dependency)
- Dedicated multi-turn diagnose harness beyond the one smoke diagnose case
- Auto-merging promoted drafts into live overlay keys (always human review)

See ADR-0015, ADR-0017, and ADR-0019 for Q&A benches, candidates, and judge/promote.
