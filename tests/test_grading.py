"""Tests for shared Q&A grading helpers."""

from __future__ import annotations

from repair_assistant.eval.grading import grade_answer, matches_citation
from repair_assistant.eval.qa_bench import QAScenarioResult, grade_scenario


def test_must_cite_all_required() -> None:
    scenario = {"must_cite": ["W11375982", "W11320651"]}
    passed, _ = grade_answer(
        scenario,
        answer="LED behaviour",
        citations=["W11375982"],
        abstained=False,
    )
    assert not passed

    passed, _ = grade_answer(
        scenario,
        answer="LED behaviour",
        citations=["tsp-w11375982", "tech-sheet-w11320651"],
        abstained=False,
    )
    assert passed


def test_matches_citation_distinguishes_revisions() -> None:
    rev_b = ["W11169652 Rev B p.44 — ACU LED"]
    rev_d = ["W11169652 Rev D"]
    bare = ["W11169652"]
    doc = ["service-manual-w11169652-revb"]
    assert matches_citation(rev_b, "W11169652 Rev B")
    assert matches_citation(doc, "W11169652 Rev B")
    assert matches_citation(rev_b, "W11169652B")
    assert not matches_citation(rev_d, "W11169652 Rev B")
    assert not matches_citation(bare, "W11169652 Rev B")
    # Bare publication still matches any revision of that pub.
    assert matches_citation(rev_b, "W11169652")
    assert matches_citation(rev_d, "W11169652")


def test_must_cite_revision_does_not_pass_on_other_rev() -> None:
    scenario = {"must_cite": ["W11169652 Rev B"]}
    passed, detail = grade_answer(
        scenario,
        answer="See the revised manual.",
        citations=["W11169652 Rev D"],
        abstained=False,
    )
    assert not passed
    assert "must_cite" in detail

    passed, _ = grade_answer(
        scenario,
        answer="See the revised manual.",
        citations=["W11169652 Rev B"],
        abstained=False,
    )
    assert passed


def test_fails_if_contains() -> None:
    scenario = {"fails_if_contains": ["slow blink is a fault"]}
    passed, detail = grade_answer(
        scenario,
        answer="The slow blink is a fault condition.",
        citations=[],
        abstained=False,
    )
    assert not passed
    assert "fails_if" in detail


def test_fails_if_skipped_when_abstained() -> None:
    scenario = {"fails_if_contains": ["samsung"], "expect_abstain": True}
    passed, detail = grade_answer(
        scenario,
        answer="ABSTAIN: No evidence for Samsung dishwasher draining.",
        citations=[],
        abstained=True,
    )
    assert passed, detail


def test_must_not_cite_as_current_blocks_uncqualified_cite() -> None:
    scenario = {"must_not_cite_as_current": ["W11156989"]}
    bad, detail = grade_answer(
        scenario,
        answer="See the safety notice in W11156989.",
        citations=["W11156989"],
        abstained=False,
    )
    assert not bad
    assert "must_not_cite_as_current" in detail

    ok, _ = grade_answer(
        scenario,
        answer="W11156989 is superseded; use W11320651 for this notice.",
        citations=["W11156989", "W11320651"],
        abstained=False,
    )
    assert ok


def test_grade_scenario_adapter() -> None:
    result = QAScenarioResult(
        scenario_id="x",
        passed=False,
        answer="door lock",
        citations=["W11320651"],
    )
    passed, _ = grade_scenario({"expect_contains": ["door lock"]}, result)
    assert passed
