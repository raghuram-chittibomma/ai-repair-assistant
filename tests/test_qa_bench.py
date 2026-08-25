"""Unit tests for Q&A smoke grader (no live API)."""

from __future__ import annotations

from repair_assistant.eval.qa_bench import QAScenarioResult, grade_scenario


def test_grade_expect_contains_and_cites() -> None:
    scenario = {
        "id": "x",
        "expect_contains": ["door lock"],
        "expect_cites_any": ["W11320651"],
    }
    result = QAScenarioResult(
        scenario_id="x",
        passed=False,
        answer="F5E2 is a door lock fault.",
        citations=["tech-sheet-w11320651", "W11320651"],
    )
    passed, detail = grade_scenario(scenario, result)
    assert passed
    assert detail == "ok"


def test_grade_must_not_cite() -> None:
    scenario = {"id": "x", "must_not_cite": ["W11395614"]}
    result = QAScenarioResult(
        scenario_id="x",
        passed=False,
        answer="Door lock issue.",
        citations=["W11169652"],
    )
    passed, _ = grade_scenario(scenario, result)
    assert passed

    result.citations = ["tsp-w11395614", "W11395614"]
    passed, detail = grade_scenario(scenario, result)
    assert not passed
    assert "must_not_cite" in detail


def test_grade_expect_abstain() -> None:
    scenario = {"id": "x", "expect_abstain": True}
    result = QAScenarioResult(scenario_id="x", passed=False, abstained=True, answer="ABSTAIN: no ZZ99")
    passed, _ = grade_scenario(scenario, result)
    assert passed

    result.abstained = False
    passed, detail = grade_scenario(scenario, result)
    assert not passed
    assert "abstention" in detail
