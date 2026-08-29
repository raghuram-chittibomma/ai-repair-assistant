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
| Unit / graders (`tests/`) | strong | Strong (CI `pytest`) | Safety fixtures not executed as a suite in CI | P2 |
| Parsing (`bench-parse`, ADR-0007) | strong | Manual (PDF-local) | D3 still interim; E12 deferred (boundary guards hold) | P2 |
| Retrieval IR (`bench-retrieve`, ADR-0011/0020) | strong | Manual pass/fail (14 hard) | Measures cores only — omits `connector_fetch` / `reference_fetch` / `manual_rev_fetch`; leaders tied → weak discrimination | P0 |
| Safety (`bench-safety`, ADR-0014) | adequate | Weak in practice | Offline-capable but **not in CI** | P1 |
| Q&A smoke (`bench-qa`, ADR-0015) | adequate | Manual | Diagnose uses `turn_grades` (E7); still one smoke diagnose case | P2 |
| Candidates (`bench-candidates`, ADR-0017) | adequate | Soft | Every ready has ≥1 det rule (E2); prose-critical still need `--judge` (`requires_judge`) | P1 |
| LLM judge + promote (ADR-0019) | adequate | Opt-in | Calibration pack exists (E10); promote drafts still unused as discipline | P2 |
| Observability (Langfuse ADR-0018) | adequate | Manual | Bench spans carry `eval_bench` / `eval_run_id` / `scenario_id` (E11); failure→dataset loop is **E13 / ADR-0023** (`mine-traces`) | P2 |
| CI / release | thin | Unit + copyright only | ADR-0015 overclaimed live CI benches; EVALS.md can lag scorecard counts | P0 |
| Cross-layer consistency | adequate | n/a | Crosswalk + E4 hardness aligned; residual ID naming differences remain | P2 |

---

## Cross-cutting gaps

1. **Production ≠ bake-off path** — `bench-retrieve` → `run_strategy` omits side doors that `search()` uses (ADR-0020).
2. **Prose criteria are not full gates by default** — `grade_answer` ignores
   prose `expect`/`fails_if` unless `--judge`; ready scenarios now always have
   ≥1 det rule (E2), and prose-heavy overlays set `requires_judge`.
3. **`must_not_cite_as_current` graded** — Implemented in `grade_answer` (E5).
4. **Scenario ID / ownership mismatch** — e.g. IR `f5e2-front-load-not-top-load` vs candidates `f5e2-three-way`; IR soft serial vs candidates hard serial; synthetic supersession vs `needs_document` real case.
5. **Parse → ingest → retrieve → answer can slip** — Mitigated by thin
   `bench-chain` (E6); still one story, not a full corpus re-parse.
6. **Staleness / language / multi-hop / supersession ownership muddled** — Q&A prose vs IR cores.
7. **Diagnostic trajectory under-tested** — Mitigated by E7 (`turn_grades` +
   `diagnostic-trajectory` candidates); still thin vs ask coverage.
8. **CI vs docs drift** — Live benches manual; some ADRs/runbooks overclaim or lag.
9. **Run-log hygiene** — Mitigated by E9 (`prune-eval-runs` + runs README); still manual.
10. **Observability unlinked to eval** — Mitigated by E11 metadata on bench spans;
    Langfuse → draft-fixture loop is **E13 / ADR-0023** (`mine-traces` + replay).
11. **Ready-but-failing candidates** — Cleared in E4 (F5E2 cite relaxed;
    serial-inside deferred).
12. **Generation negative controls uneven** — Fewer “wrong-but-fluent” fails than IR/safety.

---

## Prioritized backlog

| ID | Action | Effort | Layer |
| --- | --- | --- | --- |
| **E1** | ~~IR strategy grading production `search()`~~ **Done** — `production_search` on retrieve bake-off | — | Retrieval |
| **E2** | ~~Every `ready` candidate gets ≥1 deterministic rule~~ **Done** — overlay + unit gate; `requires_judge` for prose | — | Candidates |
| **E3** | ~~Wire `bench-safety` into CI~~ **Done** — required check in `.github/workflows/ci.yml` | — | Safety / CI |
| **E4** | ~~Align IR↔candidates / ready-fail fog~~ **Done** — F5E2 `expect_cites_any`; `serial-inside-range` deferred | — | Cross-layer |
| **E5** | ~~`must_not_cite_as_current` in `grade_answer`~~ **Done** | — | Grading |
| **E6** | ~~Thin chain smoke~~ **Done** — `bench-chain` + `evals/chain/fixtures.yaml` (manual) | — | Cross-layer |
| **E7** | ~~Grade diagnose multi-turn; add diagnose candidates~~ **Done** — `turn_grades` + 3 candidates | — | Q&A / Diagnostic |
| **E8** | ~~Refresh EVALS.md / ADR-0015 CI claim / charter D4~~ **Done** (P0 docs slice) | — | Docs |
| **E9** | ~~Run-log retention~~ **Done** — `prune-eval-runs` + runs README (manual) | — | Ops |
| **E10** | ~~Judge calibration pack~~ **Done** — 10 frozen cases + `bench-judge-calibrate` | — | Judge |
| **E11** | ~~Langfuse bench metadata~~ **Done** — `eval_bench` / `eval_run_id` / `scenario_id` | — | Observability |
| **E12** | **Thin reopen (ADR-0022)** — contextual enrichment + bounded audit/repair; not a full D4 chunker bake | 2026-08-27 | Parsing |
| **E13** | ~~Langfuse mine → draft evals~~ **Done** — ADR-0023 `mine-traces` (stamp + window + replay; analysis report; human promote) | — | Observability / Eval |

**Suggested first slice:** E8 → E5 → E4 → E1 (E3 done — `bench-safety` is a CI gate).

**Slice status (2026-08-29):** Eval-framework backlog **closed** for the
audited slice. E3 done (`bench-safety` in CI); E12 deferred (no boundary failure).
**E4 done** — `f5e2-three-way` uses `expect_cites_any` (wrong-KB bans kept);
`serial-inside-range` is `status: deferred` to match soft IR. No remaining
open E-items from that audit (**E13** added later as Phase 11).

**E12 update (2026-08-27):** Reopened thinly for Langfuse-observed opaque
numeric table rows (`14 | -10 | 111.6` without column labels). ADR-0022 keeps
ADR-0007 split boundaries; enriches embed/LLM text with doc/section/headers;
`audit_and_improve` allows at most one repair pass (no while-loop). Binding
fixtures must stay PASS.

**E13 (Phase 11):** Implemented — `mine-traces` classifies Langfuse traces,
replays on current code (`resolved_stale` when fixed), and writes a reviewable
analysis report under `evals/qa/drafts/` (`mine-report-*.md`). See
[ADR-0023](adr/0023-trace-driven-eval-mining.md).

### E12 reopen triggers (then thin micro-bake, not a full D4 redo)

Reopen **further** chunking work only if any of these regress under the
**default** extractor / production path:

1. `bench-parse` fixture `error-codes-bound` fails (F6E1 / F8E1 unbound)
2. IR `error-code-f6e1` fails on `production_search` or `vector_apply_boost`
3. Candidate `error-code-orphaned-by-extraction` fails det grading
4. `bench-chain` fails in a way that points at severed code↔remedy chunks

ADR-0022 enrichment is the accepted thin response to opaque numeric rows;
do not invent a full splitter bake without the triggers above.

---

## Explicit non-gaps

- ADR bake-off-before-default posture
- Retrieval fixture design + synthetic isolation (`synth-` / `SYNTH-`)
- Deterministic grader first; judge opt-in (ADR-0019)
- `promote-eval` draft-only (no auto-merge)
- Safety fixture quality; ranking unit tests
- Docling non-default; hybrid default for parse (ADR-0024); retrieval hybrid-as-default (ADR-0020)
- Chunking micro-bake without a boundary/chain failure (full D4 still deferred; ADR-0022 is the thin path)

---

## Follow-on bake-offs?

| Topic | Warranted? | Why |
| --- | --- | --- |
| Chunking | **Thin (ADR-0022)** | Contextual enrichment + bounded quality; full splitter bake still only on E12 triggers |
| Retrieval strategy | No | `production_search` already on the IR bake-off (E1) |
| Judge calibration | Done (E10) | 10-case pack + `bench-judge-calibrate` |

---

## Sources

- `docs/EVALS.md`, `docs/CHARTER.md`, ADRs 0007 / 0010 / 0011 / 0015 / 0018 / 0019 / 0020
- `evals/parsing|retrieval|safety|qa|scenarios/`
- `src/repair_assistant/eval/`, `retrieval/bench.py`, `retrieval/search.py`
- `.github/workflows/ci.yml`
