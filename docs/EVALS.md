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

Hard corpus scenarios live in `evals/scenarios/candidates.yaml` (`status: ready`).
Deterministic overlays for the candidate bench are in
`evals/qa/candidates-grading.yaml`. Prose `fails_if` / `expect` fields remain for
human review unless an overlay encodes them.

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
```

Optional: re-run a single scenario

```powershell
python -m repair_assistant.corpus.cli bench-qa --write --scenario acu-led-step-10
python -m repair_assistant.corpus.cli bench-candidates --write --scenario installation-fault-not-component-fault
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
- LLM-as-judge for prose `fails_if` rules
- Dedicated multi-turn diagnose harness beyond the one smoke diagnose case
- Auto-wiring production failures into fixtures (add scenarios by hand when useful)

See ADR-0015 and ADR-0017 for how the Q&A and candidate benches were introduced.
