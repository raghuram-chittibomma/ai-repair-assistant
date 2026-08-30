# ADR-0033: Judge model is not the generator; verdicts may abstain

## Status

Accepted — review R30 (Reduce).

## Context

The prose judge (`--judge`, `bench-judge-calibrate`) used `llm_model()` — the
same dated snapshot as ask/diagnose. Review R30: self-preference bias is
unmitigated; the verdict is binary with no abstention; the 10-case calibration
pack cannot detect drift; inter-annotator agreement needs more than one
annotator.

The last two are constraint blockers (single developer, no labelling
programme). Model diversity and abstention are not.

Live OpenAI `response_format` after ADR-0028 also forced the judge through
`grounded_answer`, which has no `passed` field.

## Decision

1. **`JUDGE_LLM_MODEL`** defaults to a dated snapshot **different from**
   `LLM_MODEL` (`gpt-4.1-mini-2025-04-14` vs `gpt-4o-mini-2024-07-18`).
   Override to the generator only if you accept the bias. Scorecards stamp
   both.
2. **Verdicts are `pass` / `fail` / `abstain`.** Abstain does not fail a
   scenario that already passed deterministic grading; the detail records it.
   Calibration treats abstain as disagreement with a labelled pass/fail.
3. **Judge JSON schema** is `judge_verdict`, not `grounded_answer`. The parser
   still accepts legacy `{"passed": true}` for tests.
4. **Position:** the user prompt lists criteria (fails_if before expect), then
   evidence, then the answer.
5. **Out of scope:** expanding the calibration pack to ~100 cases;
   inter-annotator agreement. Recorded as the Reduce remainder.

**Charter:** evaluator philosophy — do not treat a judge score as objective.
No deviation.

## Consequences

- `--judge` costs a second model id; operators must have access to that
  snapshot or set `JUDGE_LLM_MODEL`.
- Drift detection stays limited to the 10 frozen cases plus human reading.
