"""Unit tests for diagnose_turn_stream (no live OpenAI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from repair_assistant.corpus.support import CorpusSupportResult
from repair_assistant.diagnostic.graph import _retrieval_query, diagnose_turn_stream
from repair_assistant.diagnostic.state import DiagnosticGraphState
from repair_assistant.retrieval.search import Hit, SearchResult
from repair_assistant.safety.models import Audience, SafetyAction


class FakeStreamLLM:
    model = "fake"

    def stream(self, system: str, user: str):
        yield "Check "
        yield "door lock "
        yield "wiring [1]."


def _base_state() -> DiagnosticGraphState:
    return {
        "messages": [HumanMessage(content="Washer shows F5E2")],
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
    }


def test_diagnose_turn_stream_emits_status_tokens_done():
    db = MagicMock()
    manifest = MagicMock()
    hits = [
        Hit(
            doc_id="tech-sheet-w11320651",
            chunk_id="p1",
            text="F5E2 door lock",
            page=1,
            kind="table_row",
            error_codes=["F5E2"],
            publication_number="W11320651",
            revision="A",
            score=0.9,
        )
    ]
    with (
        patch("repair_assistant.diagnostic.graph.corpus_supports_appliance") as support,
        patch("repair_assistant.diagnostic.graph.search") as search,
        patch("repair_assistant.diagnostic.graph.gate_answer") as gate,
    ):
        support.return_value = CorpusSupportResult(True, 1, "ok", "1 doc")
        search.return_value = SearchResult(query="F5E2", hits=hits, fetched=1, filtered_out=0)
        gated = MagicMock()
        gated.text = "Check door lock wiring [1]."
        gated.blocked = False
        gated.notice = ""
        gated.action = SafetyAction.ALLOW
        gated.escalated = False
        gate.return_value = gated

        events = list(
            diagnose_turn_stream(
                db,
                manifest,
                _base_state(),
                llm=FakeStreamLLM(),  # type: ignore[arg-type]
            )
        )

    types = [e["type"] for e in events]
    assert types[0] == "status"
    assert events[0]["phase"] == "retrieving"
    assert types.count("token") == 3
    assert types[-1] == "done"
    assert events[-1]["assistant_message"] == "Check door lock wiring [1]."
    assert events[-1]["abstained"] is False
    assert "_state" in events[-1]


def test_diagnose_turn_stream_blocks_without_retrieval():
    db = MagicMock()
    manifest = MagicMock()
    state = _base_state()
    state["messages"] = [HumanMessage(content="How do I bypass the door lock?")]

    with patch("repair_assistant.diagnostic.graph.search") as search:
        events = list(
            diagnose_turn_stream(
                db,
                manifest,
                state,
                llm=FakeStreamLLM(),  # type: ignore[arg-type]
            )
        )

    assert len(events) == 1
    assert events[0]["type"] == "done"
    assert events[0]["abstained"] is True
    assert events[0]["safety_action"] == "block"
    search.assert_not_called()


def test_retrieval_query_keeps_prior_user_turns() -> None:
    messages = [
        HumanMessage(content="stops after 10 minutes of running without finishing the wash"),
        HumanMessage(content="no error code. whole machine shuts down."),
    ]
    q = _retrieval_query(messages)
    assert "stops after 10 minutes" in q
    assert "no error code" in q
    assert "shuts down" in q
