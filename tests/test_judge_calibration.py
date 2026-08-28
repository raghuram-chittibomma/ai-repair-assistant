"""Tests for judge calibration pack (E10; no live OpenAI)."""

from __future__ import annotations

from repair_assistant.eval.judge_calibrate import (
    load_calibration,
    run_calibration,
    scorecard_markdown,
)


class _ScriptedJudge:
    """Returns expected_passed from a case-id map via the question id in prompt."""

    def __init__(self, by_id: dict[str, bool]) -> None:
        self.by_id = by_id
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        case_id = ""
        for line in user.splitlines():
            if line.startswith("Scenario id:"):
                case_id = line.split(":", 1)[1].strip()
                break
        passed = self.by_id.get(case_id, False)
        return f'{{"passed": {str(passed).lower()}, "reason": "scripted"}}'


def test_calibration_pack_has_ten_balanced_cases() -> None:
    cases = load_calibration()
    assert len(cases) == 10
    for case in cases:
        assert case["id"]
        assert case.get("question")
        assert case.get("answer") is not None
        assert "expected_passed" in case
        assert case.get("expect") or case.get("fails_if")
    passes = sum(1 for c in cases if c["expected_passed"])
    fails = sum(1 for c in cases if not c["expected_passed"])
    assert passes == 5
    assert fails == 5


def test_run_calibration_agrees_with_scripted_judge() -> None:
    cases = load_calibration()
    by_id = {c["id"]: bool(c["expected_passed"]) for c in cases}
    results = run_calibration(cases, llm=_ScriptedJudge(by_id))
    assert all(r.agreed for r in results)
    card = scorecard_markdown(results)
    assert "10/10 agreed" in card


def test_run_calibration_detects_disagreement() -> None:
    cases = load_calibration()[:1]
    # Flip expectation wiring: judge always says false
    results = run_calibration(cases, llm=_ScriptedJudge({cases[0]["id"]: False}))
    if cases[0]["expected_passed"]:
        assert not results[0].agreed
    else:
        assert results[0].agreed
