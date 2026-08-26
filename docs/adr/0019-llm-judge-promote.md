# ADR-0019: LLM-as-judge and failure promotion

## Status

Accepted

## Context

ADR-0015 delivered deterministic Q&A grading and JSON run logs. Charter Phase 9
still deferred LLM-judged prose criteria (`expect` / `fails_if` in
`evals/scenarios/candidates.yaml`) and a path to fold production/bench failures
back into fixtures. Operators already run benches manually ([EVALS.md](../EVALS.md)).

## Decision

1. **Opt-in LLM-as-judge** via `--judge` on `bench-qa` and `bench-candidates`.
   Deterministic rules always run first. The judge only evaluates prose
   `expect` / `fails_if` when deterministic grading already passed.
2. **`promote-eval`** reads a failed run JSON and drafts a grading-overlay stub
   under `candidates-grading.yaml` → `scenarios.<id>.draft` (or prints YAML).
   Humans review and promote useful keys; drafts are never live gates.
3. Benches remain **manual** (no CI live OpenAI). Judge uses the same
   `OPENAI_API_KEY` / `LLM_MODEL` as `ask`.

## Consequences

- Prose criteria become enforceable without rewriting every scenario as
  substring lists.
- Failure → fixture loop is explicit and reviewable, matching the charter
  “connect failures back into the evaluation dataset” intent without auto-merge.
- Extra OpenAI cost only when `--judge` is requested.

## Alternatives considered

- Always-on judge: rejected (cost, flakiness on every smoke run).
- Auto-append to live overlay: rejected (risk of baking bad heuristics).
