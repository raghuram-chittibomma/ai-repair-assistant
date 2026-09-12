"""Closed-set diagnose retrieve labels (ADR-0039) — no live OpenAI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from repair_assistant.diagnostic.graph import _retrieval_query, retrieve_diagnose_state
from repair_assistant.diagnostic.intent import (
    classify_diagnose_turn,
    last_doc_ids_from_citations,
    parse_diagnose_label,
    query_for_label,
    stick_diagnose_hits,
)
from repair_assistant.diagnostic.state import DiagnosticGraphState
from repair_assistant.retrieval.search import Hit
from repair_assistant.safety.models import Audience, SafetyAction


def _hit(doc_id: str, text: str, *, score: float = 0.5) -> Hit:
    return Hit(
        doc_id=doc_id,
        chunk_id=f"{doc_id}-1",
        text=text,
        page=10,
        kind="table_row",
        error_codes=["F5E2"],
        publication_number=doc_id.split("-")[-1].upper() if "-" in doc_id else None,
        revision="B",
        score=score,
    )


def test_parse_diagnose_label_accepts_json_and_rejects_unknown() -> None:
    assert parse_diagnose_label('{"label": "still_unresolved"}') == "still_unresolved"
    assert parse_diagnose_label("```json\n{\"label\": \"ack\"}\n```") == "ack"
    assert parse_diagnose_label('{"label": "rewrite this query"}') is None
    assert parse_diagnose_label("") is None


def test_query_for_label_uses_anchor_not_followup_text() -> None:
    q = query_for_label(
        "still_unresolved",
        anchor="Washer shows F5E2 and the door will not lock.",
        latest="checked but still facing the issue",
        codes=["F5E2"],
    )
    assert "F5E2" in q
    assert "door will not lock" in q
    assert "still facing" not in q


def test_query_for_label_new_symptom_uses_latest() -> None:
    q = query_for_label(
        "new_symptom",
        anchor="doesn't wash properly",
        latest="actually wash stops halfway thru",
        codes=[],
    )
    assert "stops halfway" in q
    assert "doesn't wash" not in q


def test_query_for_label_mid_cycle_uses_latest() -> None:
    q = query_for_label(
        "mid_cycle_stop",
        anchor="doesn't wash properly",
        latest="stops after 10 minutes no error code",
        codes=[],
    )
    assert "stops after 10 minutes" in q


def test_classify_none_complete_falls_back() -> None:
    assert classify_diagnose_turn(board_text="", transcript="User: hi") is None


def test_classify_uses_injected_complete() -> None:
    label = classify_diagnose_turn(
        board_text="ruled out: door lock",
        transcript="User: F5E2\nAssistant: check lock\nUser: still facing the issue",
        complete=lambda _s, _u: '{"label": "still_unresolved"}',
    )
    assert label == "still_unresolved"


def test_classify_invalid_json_falls_back() -> None:
    assert (
        classify_diagnose_turn(
            board_text="",
            transcript="User: x",
            complete=lambda _s, _u: "not-json",
        )
        is None
    )


def test_stick_prefers_last_doc_and_demotes_other_pub_overlap() -> None:
    manual = _hit(
        "service-manual-w11169652-revb",
        "Next cause: drain pump filter clogged",
        score=0.4,
    )
    sheet = _hit(
        "tech-sheet-w11320651",
        "Possible cause: Door lock mechanism not functioning",
        score=0.9,
    )
    other = _hit("tsp-w11375982", "unrelated pointer note", score=0.8)
    ordered = stick_diagnose_hits(
        [sheet, other, manual],
        prefer_doc_ids=["service-manual-w11169652-revb"],
        demote_texts=["Door lock mechanism not functioning"],
    )
    assert [h.doc_id for h in ordered] == [
        "service-manual-w11169652-revb",
        "tsp-w11375982",
        "tech-sheet-w11320651",
    ]


def test_stick_demotes_completed_check_even_on_preferred_doc() -> None:
    same = _hit(
        "service-manual-w11169652-revb",
        "TEST #4: Door Lock System. Check door lock mechanism.",
        score=0.9,
    )
    nxt = _hit(
        "service-manual-w11169652-revb",
        "Next cause: drain pump filter clogged",
        score=0.3,
    )
    ordered = stick_diagnose_hits(
        [same, nxt],
        prefer_doc_ids=["service-manual-w11169652-revb"],
        demote_texts=["TEST #4: Door Lock System on page 15"],
    )
    assert ordered[0].text.startswith("Next cause")
    assert "TEST #4" in ordered[-1].text


def test_demote_texts_include_test_number_from_prior_reply() -> None:
    from repair_assistant.diagnostic.intent import demote_texts_from_board

    needles = demote_texts_from_board(
        {"ruled_out": [], "next_check": ""},
        extra=["Proceed with TEST #4: Door Lock System on page 15 [4]."],
    )
    assert "test #4" in needles


def test_retrieval_query_fallback_still_used_without_label() -> None:
    messages = [
        HumanMessage(content="F5E2 door won't lock"),
        HumanMessage(content="checked but still facing the issue"),
    ]
    q = _retrieval_query(messages)
    assert "F5E2" in q
    assert "still facing" not in q


def test_retrieve_uses_injected_label_not_followup_tokens() -> None:
    state: DiagnosticGraphState = {
        "messages": [
            HumanMessage(content="Washer shows F5E2 and the door will not lock."),
            AIMessage(content="Check the door lock [1]."),
            HumanMessage(content="checked but still facing the issue"),
        ],
        "appliance_model": "WFW5620HW0",
        "appliance_serial": None,
        "audience": Audience.OWNER.value,
        "retrieval_query": "",
        "evidence_text": "",
        "citations_available": [],
        "retrieval_count": 0,
        "abstained": False,
        "abstain_reason": "",
        "safety_action": SafetyAction.ALLOW.value,
        "safety_notice": "",
        "safety_rule_id": "allow",
        "prompt_directive": "",
        "escalated": False,
        "last_cite_doc_ids": ["service-manual-w11169652-revb"],
    }
    hits = [
        _hit("service-manual-w11169652-revb", "Next cause: drain pump", score=0.5),
        _hit(
            "tech-sheet-w11320651",
            "Possible cause: Door lock mechanism not functioning",
            score=0.9,
        ),
    ]
    with patch("repair_assistant.diagnostic.graph.search") as search:
        search.return_value = MagicMock(hits=hits, fetched=2, filtered_out=0)
        pending, needs = retrieve_diagnose_state(
            MagicMock(),
            MagicMock(),
            state,
            retrieval_limit=8,
            overfetch=40,
            classify_turn=lambda _s, _u: '{"label": "still_unresolved"}',
        )
    assert needs is True
    query = search.call_args.kwargs.get("query") or search.call_args[0][2]
    assert "F5E2" in query
    assert "still facing" not in query
    assert pending["retrieve_label"] == "still_unresolved"
    first = pending["citations_available"][0]
    assert first.doc_id == "service-manual-w11169652-revb"


def test_last_doc_ids_from_citations() -> None:
    class _C:
        def __init__(self, doc_id: str) -> None:
            self.doc_id = doc_id

    assert last_doc_ids_from_citations([_C("a"), _C("a"), _C("b")]) == ["a", "b"]
