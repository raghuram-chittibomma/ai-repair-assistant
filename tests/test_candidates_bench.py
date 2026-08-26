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
    assert "f5e2-narrow-then-exclude-24in" in ids
    assert "control-lock-before-board" in ids
    assert "f7e1-bolts-then-persist" in ids
    diagnose = [s for s in runnable if s.get("command") == "diagnose"]
    assert len(diagnose) >= 3
    assert all(s.get("turns") and s.get("turn_grades") for s in diagnose)
    assert len(runnable) >= 20
