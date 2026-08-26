"""Unit tests for Q&A smoke grader (no live API)."""

from __future__ import annotations

from types import SimpleNamespace

from repair_assistant.eval.grading import grade_diagnose_turns
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


def test_grade_diagnose_turns_per_turn() -> None:
    scenario = {
        "id": "diag",
        "turn_grades": {
            1: {"expect_contains": ["F5E2"], "must_not_cite": ["W11395614"]},
            2: {"expect_contains_any": ["test #4", "door lock"], "must_not_cite": ["W11395614"]},
        },
    }
    turns = [
        SimpleNamespace(
            turn=1,
            assistant_message="F5E2 is a door lock fault.",
            citations=["W11320651"],
            abstained=False,
        ),
        SimpleNamespace(
            turn=2,
            assistant_message="Run TEST #4 on the door lock.",
            citations=["W11169652"],
            abstained=False,
        ),
    ]
    passed, detail = grade_diagnose_turns(scenario, turns)
    assert passed, detail

    turns[1].citations = ["W11395614"]
    passed, detail = grade_diagnose_turns(scenario, turns)
    assert not passed
    assert "turn 2" in detail
    assert "must_not_cite" in detail


def test_grade_diagnose_turns_legacy_expect_turn() -> None:
    scenario = {
        "id": "diag",
        "expect_turn": 1,
        "expect_contains": ["F5E2"],
    }
    turns = [
        SimpleNamespace(turn=1, assistant_message="F5E2 means door lock.", citations=[], abstained=False),
        SimpleNamespace(turn=2, assistant_message="Check the latch.", citations=[], abstained=False),
    ]
    passed, _ = grade_diagnose_turns(scenario, turns)
    assert passed
