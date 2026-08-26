# ADR-0015: Integrated Q&A evaluation and run logging

## Status

Accepted

## Context

Phase 5–7 delivered grounded Q&A, diagnostics, and deterministic safety policy
([ADR-0012](0012-grounded-qa.md)–[0014](0014-safety-policy.md)). Hand-run smoke
checks lived in `evals/qa/smoke-scenarios.yaml` with informal markdown logs.
Charter Phase 9 requires a repeatable eval framework and run observability;
LLM-judged grading and full tracing tooling remain incremental.

Retrieval (`bench-retrieve`) and safety (`bench-safety`) already have
deterministic CI benches. Answer quality needs a live runner with structured
logs until LLM-as-judge evaluators land.

## Decision

1. **`src/repair_assistant/eval/qa_bench.py`:** load smoke scenarios, execute
   `ask` / multi-turn `diagnose`, grade with deterministic rules
   (`expect_contains`, `expect_cites_any`, `must_not_cite`, `expect_abstain`).
2. **CLI:** `repair-corpus bench-qa [--write] [--scenario ID]` — requires live
   DB + `OPENAI_API_KEY`; not CI by default.
3. **Observability:** `--write` emits `evals/qa/results/scorecard.md` and a
   timestamped JSON run log under `evals/qa/results/runs/` (answer text,
   citations, latency, pass/fail).
4. **Grader unit tests** in CI (`tests/test_qa_bench.py`) — no OpenAI calls.
5. **Deferred:** LLM-as-judge for groundedness/completeness; automated runs of
   full `evals/scenarios/candidates.yaml`. Trace exporters: see
   [ADR-0018](0018-langfuse-observability.md) (Langfuse; not LangSmith).

**Charter alignment:** implements Phase 9 (README Phase 8) incrementally. No
new deviations.

## Consequences

- Q&A regression is one command for operators with credentials; CI still covers
  grading logic and retrieval/safety benches only.
- Run JSON logs accumulate under `evals/qa/results/runs/` for post-hoc review.
- Scenario coverage stays tied to `smoke-scenarios.yaml`; expanding to charter
  candidate scenarios is a follow-on once LLM grading exists.
