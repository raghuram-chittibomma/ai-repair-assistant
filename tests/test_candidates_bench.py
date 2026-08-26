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
    assert "f5e2-three-way" in ids
    assert "f5e2-narrow-then-exclude-24in" in ids
    assert "control-lock-before-board" in ids
    assert "f7e1-bolts-then-persist" in ids
    assert "serial-inside-range" not in ids  # E4: deferred
    diagnose = [s for s in runnable if s.get("command") == "diagnose"]
    assert len(diagnose) >= 3
    assert all(s.get("turns") and s.get("turn_grades") for s in diagnose)
    assert len(runnable) >= 20


def test_f5e2_three_way_allows_manual_or_kb_cite() -> None:
    data = load_candidates()
    grading = load_grading_overlay()
    scenario = next(s for s in iter_runnable(data, grading=grading) if s["id"] == "f5e2-three-way")
    assert "kb-f5e2-front-load" not in (scenario.get("must_cite") or [])
    assert scenario.get("expect_cites_any")
    assert "kb-f5e2-top-load" in (scenario.get("must_not_cite") or [])
