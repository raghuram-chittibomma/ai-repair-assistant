# Eval framework gap review

End-to-end audit of the evaluation stack for this eval-driven repair assistant.
Date: 2026-08-26. Companion canvas: Cursor `eval-framework-gaps`.

**Verdict:** Mature for ADR-style bake-offs; not yet a closed regression system.
Biggest risk is **false coverage** — IR leaders at 14/14 on bake-off cores
(not production `search()`), many `ready` candidates auto-pass without
`--judge`, and no live benches in CI — so parse→retrieve→answer regressions
can slip between layers.

---

## Layer scorecard

| Layer | Maturity | Gate strength | Top gap | Severity |
| --- | --- | --- | --- | --- |
| Unit / graders (`tests/`) | strong | Strong (CI `pytest`) | Langfuse dotenv can defeat `test_tracing_disabled_by_default`; safety fixtures not executed as a suite in CI | P2 |
| Parsing (`bench-parse`, ADR-0007) | strong | Manual (PDF-local) | No parse→ingest→retrieve chain gate; D3 still interim | P1 |
| Retrieval IR (`bench-retrieve`, ADR-0011/0020) | strong | Manual pass/fail (14 hard) | Measures cores only — omits `connector_fetch` / `reference_fetch` / `manual_rev_fetch`; leaders tied → weak discrimination | P0 |
| Safety (`bench-safety`, ADR-0014) | adequate | Weak in practice | Offline-capable but **not in CI** | P1 |
| Q&A smoke (`bench-qa`, ADR-0015) | adequate | Manual | Only one diagnose case; later-turn notes unenforced | P1 |
| Candidates (`bench-candidates`, ADR-0017) | adequate | Soft | Every ready has ≥1 det rule (E2); prose-critical still need `--judge` (`requires_judge`) | P1 |
| LLM judge + promote (ADR-0019) | thin | Opt-in only | No calibration set; promote drafts unused as discipline | P1 |
| Observability (Langfuse ADR-0018) | thin | None for eval | Benches never score into Langfuse; no failure→dataset loop | P2 |
| CI / release | thin | Unit + copyright only | ADR-0015 overclaimed live CI benches; EVALS.md can lag scorecard counts | P0 |
| Cross-layer consistency | thin | n/a | Shared stories diverge by ID/hardness; synthetic IR ≠ real Q&A supersession | P0 |

---

## Cross-cutting gaps

1. **Production ≠ bake-off path** — `bench-retrieve` → `run_strategy` omits side doors that `search()` uses (ADR-0020).
2. **Prose criteria are not full gates by default** — `grade_answer` ignores
   prose `expect`/`fails_if` unless `--judge`; ready scenarios now always have
   ≥1 det rule (E2), and prose-heavy overlays set `requires_judge`.
3. **`must_not_cite_as_current` is dead for grading** — Present in candidates; not handled in `grade_answer`.
4. **Scenario ID / ownership mismatch** — e.g. IR `f5e2-front-load-not-top-load` vs candidates `f5e2-three-way`; IR soft serial vs candidates hard serial; synthetic supersession vs `needs_document` real case.
5. **Parse → ingest → retrieve → answer can slip** — No single chain smoke.
6. **Staleness / language / multi-hop / supersession ownership muddled** — Q&A prose vs IR cores.
7. **Diagnostic trajectory under-tested** — Smoke grades turn 1 only; candidates are `ask()` only.
8. **CI vs docs drift** — Live benches manual; some ADRs/runbooks overclaim or lag.
9. **Run-log hygiene** — Timestamped JSONs committed without retention policy.
10. **Observability unlinked to eval** — Traces ≠ benches.
11. **Ready-but-failing candidates** — Baseline 22/24 blurs gate meaning.
12. **Generation negative controls uneven** — Fewer “wrong-but-fluent” fails than IR/safety.

---

## Prioritized backlog

| ID | Action | Effort | Layer |
| --- | --- | --- | --- |
| **E1** | IR strategy/flag grading **production `search()`** (side doors); keep cores separate | M | Retrieval |
| **E2** | ~~Every `ready` candidate gets ≥1 deterministic rule~~ **Done** — overlay + unit gate; `requires_judge` for prose | — | Candidates |
| **E3** | ~~Wire `bench-safety` into CI~~ **Skipped** — all evals remain manual | — | Safety / CI |
| **E4** | Align IR↔candidates IDs + hardness; demote or fix ready-but-failing fog | S | Cross-layer |
| **E5** | Implement or drop `must_not_cite_as_current` in `grade_answer` | S | Grading |
| **E6** | Thin chain smoke: parse → ingest → retrieve → ask | M | Cross-layer |
| **E7** | Grade diagnose multi-turn; add 2–3 diagnose candidates | M | Q&A / Diagnostic |
| **E8** | Refresh EVALS.md counts, fix ADR-0015 CI claim, charter D4 staleness | S | Docs |
| **E9** | Run-log retention policy | S | Ops |
| **E10** | Small judge calibration pack (10 fixed cases) | M | Judge |
| **E11** | Attach bench run/scenario ids to Langfuse metadata | S | Observability |
| **E12** | Chunking micro-bake only if chain/boundary fails | M | Parsing / Retrieval |

**Suggested first slice:** E8 → E5 → E4 → E1 (E3 skipped — no scheduled/CI evals).

**Slice status (2026-08-26):** Report filed; docs claims corrected;
`must_not_cite_as_current` graded; IR↔candidates crosswalk; `production_search`
on the retrieve bake-off. **E3 (CI safety) skipped by policy** (all evals
manual). **E2 done** — every ready candidate has ≥1 deterministic rule via
`candidates-grading.yaml` (+ unit test); prose-heavy cases set `requires_judge`.
Next backlog: E6 / E7 / E9–E12 as needed.

---

## Explicit non-gaps

- ADR bake-off-before-default posture
- Retrieval fixture design + synthetic isolation (`synth-` / `SYNTH-`)
- Deterministic grader first; judge opt-in (ADR-0019)
- `promote-eval` draft-only (no auto-merge)
- Safety fixture quality; ranking unit tests
- Docling non-default; hybrid-as-default decision (ADR-0020)

---

## Follow-on bake-offs?

| Topic | Warranted? | Why |
| --- | --- | --- |
| Chunking | Micro only | If chain smoke or boundary-shaped IR fails — not a full D4 redo |
| Retrieval strategy | No | Grade production `search()` instead of another hybrid core bake-off |
| Judge calibration | Yes — small | 10-case agreement set before treating `--judge` as a release signal |

---

## Sources

- `docs/EVALS.md`, `docs/CHARTER.md`, ADRs 0007 / 0010 / 0011 / 0015 / 0018 / 0019 / 0020
- `evals/parsing|retrieval|safety|qa|scenarios/`
- `src/repair_assistant/eval/`, `retrieval/bench.py`, `retrieval/search.py`
- `.github/workflows/ci.yml`
