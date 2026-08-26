# ADR-0015: Integrated Q&A evaluation and run logging

## Status

Accepted

**Amended 2026-08-26:** Decision 1 still holds for live Q&A benches. The claim
that retrieval/safety are “deterministic CI benches” was wrong — CI runs
`pytest`, manifest validate, and copyright guards only. All eval benches
(`bench-safety`, `bench-retrieve`, `bench-qa`, `bench-candidates`) remain
**manual** ([EVALS.md](../EVALS.md); [EVAL_FRAMEWORK_GAPS.md](../EVAL_FRAMEWORK_GAPS.md)).
LLM-as-judge landed as opt-in ([ADR-0019](0019-llm-judge-promote.md)).

## Context

Phase 5–7 delivered grounded Q&A, diagnostics, and deterministic safety policy
([ADR-0012](0012-grounded-qa.md)–[0014](0014-safety-policy.md)). Hand-run smoke
checks lived in `evals/qa/smoke-scenarios.yaml` with informal markdown logs.
Charter Phase 9 requires a repeatable eval framework and run observability;
LLM-judged grading and full tracing tooling remain incremental.

Retrieval (`bench-retrieve`) and safety (`bench-safety`) have deterministic
**manual** scorecards. Answer quality needs a live runner with structured logs.
No eval bench is scheduled or wired into CI — operators run them by hand.

## Decision

1. **`src/repair_assistant/eval/qa_bench.py`:** load smoke scenarios, execute
   `ask` / multi-turn `diagnose`, grade with deterministic rules
   (`expect_contains`, `expect_cites_any`, `must_not_cite`, `expect_abstain`).
2. **CLI:** `repair-corpus bench-qa [--write] [--scenario ID]` — requires live
   DB + `OPENAI_API_KEY`; **not CI**.
3. **Observability:** `--write` emits `evals/qa/results/scorecard.md` and a
   timestamped JSON run log under `evals/qa/results/runs/` (answer text,
   citations, latency, pass/fail).
4. **Grader unit tests** in CI (`tests/test_qa_bench.py`) — no OpenAI calls.
5. **Deferred (partially closed):** LLM-as-judge is opt-in via `--judge`
   (ADR-0019). Automated / CI runs of retrieve, safety, candidates remain out
   of scope by operator choice. Trace exporters:
   [ADR-0018](0018-langfuse-observability.md).

**Charter alignment:** implements Phase 9 (README Phase 8) incrementally. No
new deviations.

## Consequences

- Q&A regression is one command for operators with credentials; CI covers
  grading unit tests only — **not** eval benches.
- Run JSON logs accumulate under `evals/qa/results/runs/` for post-hoc review.
- Candidate scenarios use `bench-candidates` + optional judge (ADR-0017/0019).
- Framework gaps and backlog: [EVAL_FRAMEWORK_GAPS.md](../EVAL_FRAMEWORK_GAPS.md).
