"""Tests for candidate scenario bench loader (no live API)."""

from __future__ import annotations

from repair_assistant.eval.candidates_bench import iter_runnable, load_candidates, load_grading_overlay


def test_ready_candidates_with_questions() -> None:
    data = load_candidates()
    grading = load_grading_overlay()
    runnable = iter_runnable(data, grading=grading)
    ids = {s["id"] for s in runnable}
    assert "acu-led-step-10" in ids
    assert "door-locks-wont-run-wrong-platform" in ids
    assert len(runnable) >= 20
