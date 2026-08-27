"""Tests for intent extraction and retrieval planner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from repair_assistant.corpus.manifest import Manifest
from repair_assistant.qa.generate import ask
from repair_assistant.retrieval.intent import extract_intent
from repair_assistant.retrieval.planner import check_evidence_fit, plan_retrieval
from repair_assistant.retrieval.search import Hit, SearchResult


def test_intent_door_got_locked_is_unlock_not_ambiguous() -> None:
    intent = extract_intent("door got locked", audience="owner")
    assert intent.door_polarity == "unlock"
    assert intent.needs_clarification is False
    assert intent.topic == "door_lock"


def test_intent_underspecified_door_lock_asks_clarify() -> None:
    intent = extract_intent("door lock problem", audience="owner")
    assert intent.door_polarity is None
    assert intent.needs_clarification is True
    assert intent.clarify_question
    assert "stuck closed" in intent.clarify_question.lower()


def test_plan_adds_f5e2_as_plan_code_not_user_code() -> None:
    intent = extract_intent("door got locked", audience="owner")
    plan = plan_retrieval(intent)
    assert intent.user_codes == ()
    assert plan.user_codes == ()
    assert plan.plan_codes == ("F5E2",)
    assert "F5E2" in plan.codes
    assert "will not unlock" in plan.embed_query.lower()
    assert "polarity_expand" in plan.hops
    assert plan.enable_graph_hop is False
    assert "graph" not in plan.hops


def test_user_reported_code_stays_user_code() -> None:
    intent = extract_intent("I have F5E2 and the door won't open", audience="owner")
    plan = plan_retrieval(intent)
    assert "F5E2" in intent.user_codes
    assert "F5E2" in plan.user_codes
    assert "F5E2" not in plan.plan_codes


def test_provenance_block_in_user_prompt() -> None:
    from repair_assistant.qa.generate import build_user_prompt

    prompt = build_user_prompt(
        "door got locked",
        None,
        "[1] evidence",
        user_codes=(),
        plan_codes=("F5E2",),
    )
    assert "Reported by user" in prompt
    assert "(none)" in prompt
    assert "Suggested for retrieval only" in prompt
    assert "F5E2" in prompt


def test_evidence_fit_fails_when_only_wont_lock_hits() -> None:
    intent = extract_intent("door got locked", audience="owner")
    texts = [
        "Problem: Door Won't Lock | Ensure that door is completely closed.",
        "Door not closed. Ensure that door is completely closed.",
        "Door Won't Lock possible cause door not closed.",
    ]
    fit = check_evidence_fit(intent, texts)
    assert fit.ok is False
    assert fit.clarify_question


def test_evidence_fit_ok_with_unlock_hit() -> None:
    intent = extract_intent("door got locked", audience="owner")
    texts = [
        "Door will not unlock. If Add Garment light is lit, touch START/PAUSE.",
        "Problem: Door Won't Lock | Ensure that door is completely closed.",
    ]
    assert check_evidence_fit(intent, texts).ok is True


@patch("repair_assistant.qa.generate.search")
def test_ask_clarifies_underspecified_door_lock_without_search(mock_search: MagicMock) -> None:
    db = MagicMock()
    result = ask(db, Manifest(documents=[]), "door lock issue on my washer", llm=MagicMock())
    assert result.abstain_code == "clarify"
    assert result.abstained is False
    assert "stuck closed" in result.answer.lower()
    mock_search.assert_not_called()


@patch("repair_assistant.qa.generate.search")
def test_ask_still_searches_when_polarity_clear(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(
        query="door got locked",
        hits=[
            Hit(
                doc_id="use-and-care",
                chunk_id="u1",
                text="Door will not unlock. Touch START/PAUSE once.",
                page=26,
                kind="table_row",
                error_codes=[],
                publication_number="W11156985",
                revision="A",
                score=0.9,
            )
        ],
    )
    llm = MagicMock()
    llm.complete.return_value = "Try START/PAUSE to unlock [1]."
    db = MagicMock()
    result = ask(db, Manifest(documents=[]), "door got locked", llm=llm)
    mock_search.assert_called_once()
    assert result.retrieval_count == 1
    assert "clarify" not in (result.abstain_code or "")
