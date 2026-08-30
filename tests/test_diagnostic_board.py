"""Diagnostic board merge and trajectory grading (ADR-0031 / R31)."""

from __future__ import annotations

from types import SimpleNamespace

from repair_assistant.diagnostic.board import (
    DiagnosticBoard,
    DiagnosticDelta,
    format_board,
    merge_board,
    merge_from_raw,
)
from repair_assistant.eval.grading import grade_diagnose_turns


def test_merge_records_user_observation_without_model_delta() -> None:
    board = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="Washer shows F5E2",
        user_message="Washer shows F5E2",
    )
    assert board.step == 1
    assert board.symptom_anchor == "Washer shows F5E2"
    assert board.observations[0].source == "user"
    assert "F5E2" in board.observations[0].text
    assert board.ruled_out == []
    text = format_board(board)
    assert "ruled out: (none yet)" in text


def test_merge_unions_ruled_out_and_drops_hypothesis() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="dead panel",
        user_message="buttons do nothing",
        delta=DiagnosticDelta(
            phase="next_step",
            hypotheses=["control lock", "HMI failure"],
            next_check="hold Control Lock 3 seconds",
        ),
    )
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="dead panel",
        user_message="I held Control Lock and LOC is gone",
        delta=DiagnosticDelta(
            phase="causes",
            hypotheses=["HMI failure"],
            ruled_out=["control lock"],
            next_check="TEST #2 HMI communication",
        ),
    )
    assert board.step == 2
    assert board.phase == "causes"
    assert board.ruled_out == ["control lock"]
    assert board.hypotheses == ["HMI failure"]
    assert "control lock" not in " ".join(board.hypotheses).lower()
    assert board.symptom_anchor == "dead panel"


def test_merge_from_raw_reads_structured_diagnostic() -> None:
    raw = """
    {"abstained": false, "abstain_reason": "",
     "answer": "Check the door lock [1].",
     "claims": [{"text": "Check the door lock", "evidence_index": 1}],
     "diagnostic": {"phase": "next_step", "hypotheses": ["door lock"],
      "ruled_out": [], "observations": ["door locked"],
      "next_check": "TEST #4"}}
    """
    board = merge_from_raw(
        None,
        step=1,
        symptom_anchor="F5E2",
        user_message="F5E2 on display",
        raw=raw,
    )
    assert board.phase == "next_step"
    assert board.hypotheses == ["door lock"]
    assert board.next_check == "TEST #4"
    assert any(obs.text == "door locked" for obs in board.observations)


def test_grade_board_keys() -> None:
    turns = [
        SimpleNamespace(
            turn=1,
            assistant_message="Hold Control Lock [1].",
            citations=["W11169652"],
            abstained=False,
            diagnostic={
                "phase": "next_step",
                "ruled_out": [],
                "hypotheses": ["control lock"],
            },
        ),
        SimpleNamespace(
            turn=2,
            assistant_message="Try TEST #2 [1].",
            citations=["W11320651"],
            abstained=False,
            diagnostic={
                "phase": "causes",
                "ruled_out": ["control lock"],
                "hypotheses": ["HMI"],
            },
        ),
    ]
    passed, detail = grade_diagnose_turns(
        {
            "turn_grades": {
                2: {
                    "expect_contains": ["TEST #2"],
                    "expect_phase": "causes",
                    "expect_ruled_out_any": ["control lock"],
                    "expect_hypotheses_any": ["HMI"],
                }
            }
        },
        turns,
    )
    assert passed, detail
    turns[1].diagnostic["ruled_out"] = []
    passed, detail = grade_diagnose_turns(
        {
            "turn_grades": {
                2: {"expect_ruled_out_any": ["control lock"]}
            }
        },
        turns,
    )
    assert not passed
    assert "expect_ruled_out_any" in detail
