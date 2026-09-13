"""Diagnostic board merge and trajectory grading (ADR-0031 / R31)."""

from __future__ import annotations

from types import SimpleNamespace

from repair_assistant.diagnostic.board import (
    DiagnosticBoard,
    DiagnosticDelta,
    display_check_label,
    exhausted_path_close_message,
    format_board,
    merge_board,
    merge_from_raw,
    session_tally,
    should_close_exhausted_pointer,
    tally_cleared,
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


def test_merge_ack_rules_out_prior_next_check() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="doesn't wash properly",
        user_message="doesn't wash properly",
        delta=DiagnosticDelta(
            phase="next_step",
            hypotheses=["excess detergent", "drain obstruction"],
            next_check="Check drain hose and filter; avoid excess detergent",
        ),
    )
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="doesn't wash properly",
        user_message="checked. those look good",
    )
    assert board.ruled_out == [
        "Check drain hose and filter; avoid excess detergent"
    ]
    assert board.next_check == ""


def test_merge_ack_rules_out_numbered_checks_from_prior_assistant() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="doesn't wash properly",
        user_message="doesn't wash properly",
        delta=DiagnosticDelta(phase="next_step", next_check="correct dispenser usage"),
    )
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="doesn't wash properly",
        user_message="checked those look good",
        prior_assistant=(
            "Check these first [1].\n"
            "1. Load bunching\n"
            "2. Use of HE detergent\n"
            "3. Correct wash cycle\n"
            "4. Correct dispenser usage [1]"
        ),
    )
    assert "Use of HE detergent" in board.ruled_out
    assert "Load bunching" in board.ruled_out
    assert "correct dispenser usage" in board.ruled_out


def test_merge_ack_rules_out_inline_numbered_category() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="door doesn't open",
        user_message="door doesn't open",
        delta=DiagnosticDelta(phase="next_step", next_check="Reset washer"),
    )
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="door doesn't open",
        user_message="checked all. no issues there",
        prior_assistant=(
            "Possible causes and checks: 1. **Reset washer**: Unplug and "
            "reconnect the power cord. 2. **Check door lock mechanism**: "
            "Inspect for misalignment. 3. **Door lock mechanism not "
            "functioning**: See TEST #4 [1]."
        ),
    )
    assert any("Reset washer" in item for item in board.ruled_out)
    assert any("door lock mechanism" in item.lower() for item in board.ruled_out)
    assert board.next_check == ""
    assert any("test #4" in item.lower() for item in board.ruled_out)
    assert should_close_exhausted_pointer(
        board, evidence_text="See TEST #4: Door Lock System."
    )


def test_merge_ack_rules_out_see_test_pointer_without_numbers() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=2,
        symptom_anchor="will not drain",
        user_message="checked. those look good",
        delta=DiagnosticDelta(
            phase="next_step",
            next_check="See TEST #8: Drain/Recirculation Pump",
        ),
    )
    board = merge_board(
        prior,
        step=3,
        symptom_anchor="will not drain",
        user_message="checked, no issues there",
        prior_assistant=(
            "Proceed to TEST #8: Drain/Recirculation Pump for further "
            "diagnostics [1]."
        ),
    )
    assert any("test #8" in item.lower() for item in board.ruled_out)
    assert board.next_check == ""


def test_merge_ack_clears_repeated_see_test_next_check() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=2,
        symptom_anchor="will not drain",
        user_message="checked. those look good",
        delta=DiagnosticDelta(phase="next_step", next_check=""),
    )
    board = merge_board(
        prior,
        step=3,
        symptom_anchor="will not drain",
        user_message="checked, no issues there",
        prior_assistant="Proceed to TEST #8: Drain/Recirculation Pump [1].",
        delta=DiagnosticDelta(
            phase="next_step",
            next_check="See TEST #8: Drain/Recirculation Pump",
        ),
    )
    assert any("test #8" in item.lower() for item in board.ruled_out)
    assert board.next_check == ""


def test_merge_ack_label_harvests_when_regex_misses() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="will not drain",
        user_message="will not drain",
        delta=DiagnosticDelta(phase="next_step", next_check=""),
    )
    skipped = merge_board(
        prior,
        step=2,
        symptom_anchor="will not drain",
        user_message="the checks were negative",
        prior_assistant="Proceed to TEST #8: Drain/Recirculation Pump [1].",
    )
    assert skipped.ruled_out == []
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="will not drain",
        user_message="the checks were negative",
        prior_assistant="Proceed to TEST #8: Drain/Recirculation Pump [1].",
        intent_label="ack",
    )
    assert any("test #8" in item.lower() for item in board.ruled_out)


def test_close_when_pack_see_test_already_ruled_out() -> None:
    board = merge_board(
        DiagnosticBoard(),
        step=2,
        symptom_anchor="will not drain",
        user_message="checked, no issues there",
        prior_assistant="Proceed to TEST #8: Drain/Recirculation Pump [1].",
    )
    evidence = (
        "[1] Possible cause: Pump not pumping. See TEST #8: "
        "Drain/Recirculation Pump."
    )
    assert should_close_exhausted_pointer(board, evidence_text=evidence)
    assert "no further grounded steps" in exhausted_path_close_message(board)
    unused = merge_board(
        DiagnosticBoard(),
        step=2,
        symptom_anchor="will not drain",
        user_message="checked, no issues there",
        prior_assistant="1. Check the drain hose [1].",
    )
    assert not should_close_exhausted_pointer(unused, evidence_text=evidence)


def test_merge_unresolved_rules_out_prior_next_check() -> None:
    prior = merge_board(
        DiagnosticBoard(),
        step=1,
        symptom_anchor="F5E2 door won't lock",
        user_message="F5E2 door won't lock",
        delta=DiagnosticDelta(
            phase="next_step",
            hypotheses=["door lock mechanism"],
            next_check="Check door lock mechanism for proper operation",
        ),
    )
    board = merge_board(
        prior,
        step=2,
        symptom_anchor="F5E2 door won't lock",
        user_message="checked but still facing the issue",
    )
    assert board.ruled_out == [
        "Check door lock mechanism for proper operation"
    ]
    assert board.next_check == ""


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


def test_tally_formats_needles_and_drops_duplicate_test() -> None:
    assert display_check_label("test #4") == "See TEST #4"
    assert tally_cleared(
        [
            "Reset washer",
            "Door lock mechanism not functioning: See TEST #4",
            "test #4",
        ]
    ) == ["Reset washer", "Door lock mechanism not functioning: See TEST #4"]


def test_session_tally_closed_omits_next_and_uses_pack_cite() -> None:
    board = DiagnosticBoard(
        phase="close",
        symptom_anchor="will not drain",
        ruled_out=["Check the drain hose", "test #8"],
        next_check="See TEST #8: Drain/Recirculation Pump",
    )
    cite = SimpleNamespace(
        index=1,
        label="W11320651 Rev B",
        doc_id="tech-sheet-example",
        page=10,
    )
    tally = session_tally(board, [cite])
    assert tally["symptom"] == "will not drain"
    assert tally["cleared"] == ["Check the drain hose", "See TEST #8"]
    assert tally["closed"] is True
    assert tally["next"] == ""
    assert tally["offered"] == []
    assert tally["citation_index"] == 1
    assert tally["citation_page"] == 10


def test_session_tally_offers_numbered_checks_before_ack() -> None:
    board = DiagnosticBoard(
        phase="next_step",
        symptom_anchor="door doesn't open",
        next_check="Reset washer",
    )
    cite = SimpleNamespace(index=1, label="W11320651 Rev B", doc_id="tech-sheet", page=10)
    tally = session_tally(
        board,
        [cite],
        assistant=(
            "1. Reset washer: unplug. 2. Check the door lock mechanism. "
            "3. See TEST #4 [1]."
        ),
    )
    assert tally["symptom"] == "door doesn't open"
    assert tally["cleared"] == []
    assert any("Reset washer" in item for item in tally["offered"])
    assert any("TEST #4" in item for item in tally["offered"])
