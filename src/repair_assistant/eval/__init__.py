"""Evaluation harness for grounded Q&A (Phase 8)."""

from repair_assistant.eval.qa_bench import (
    QAScenarioResult,
    grade_scenario,
    run_smoke_bench,
    scorecard_markdown,
)

__all__ = ["QAScenarioResult", "grade_scenario", "run_smoke_bench", "scorecard_markdown"]
