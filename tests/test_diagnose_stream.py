"""Unit tests for diagnose_turn_stream (no live OpenAI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

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
    # Deltas are released through the safety stream gate (R1), so token events no
    # longer map one-to-one onto model deltas. What must hold is that the text
    # delivered is exactly the text generated.
    assert types.count("token") >= 1
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed == "Check door lock wiring [1]."
    assert types[-1] == "done"
    assert events[-1]["assistant_message"] == "Check door lock wiring [1]."
    assert events[-1]["abstained"] is False
    assert events[-1]["diagnostic"]["step"] == 1
    assert events[-1]["diagnostic"]["symptom_anchor"]
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


def test_retrieval_query_ack_keeps_symptom_anchor() -> None:
    from repair_assistant.qa.acks import is_ack_only_message

    assert is_ack_only_message("no issues from these checks")
    assert is_ack_only_message("no issues there")
    assert is_ack_only_message("this also looks good")
    assert is_ack_only_message("those look good")
    assert is_ack_only_message("checked. those look good")
    assert is_ack_only_message("checked those look good")
    assert is_ack_only_message("checked, they look good")
    assert is_ack_only_message("they look good")
    assert is_ack_only_message("checked all. no issues there")
    assert is_ack_only_message("checked all no issues there")
    assert is_ack_only_message("checked all, no issues found there")
    assert is_ack_only_message("checked. no issue there as well")
    assert not is_ack_only_message("no error code. whole machine shuts down.")
    from repair_assistant.qa.acks import is_unresolved_followup

    assert is_unresolved_followup("checked but still facing the issue")
    assert is_unresolved_followup("checked, still facing same issue")
    assert is_unresolved_followup("still facing the issue")
    assert is_unresolved_followup("tried but did not solve the problem")
    assert is_unresolved_followup("tried but it didn't work")
    assert is_unresolved_followup("that didn't work")
    assert not is_unresolved_followup("still not draining")
    assert not is_unresolved_followup("no error code. whole machine shuts down.")
    assert not is_unresolved_followup("tried a new hose but still not draining")

    messages = [
        HumanMessage(content="doesn't wash properly"),
        HumanMessage(content="no issues from these checks"),
        HumanMessage(content="this also looks good"),
    ]
    q = _retrieval_query(messages)
    assert "doesn't wash properly" in q
    assert "no issues" not in q
    assert "looks good" not in q


def test_retrieval_query_checked_all_keeps_anchor() -> None:
    messages = [
        HumanMessage(content="door doesn't open"),
        HumanMessage(content="checked all. no issues there"),
    ]
    q = _retrieval_query(messages)
    assert "door" in q.lower()
    assert "checked all" not in q.lower()


def test_retrieval_query_unresolved_keeps_symptom_anchor() -> None:
    messages = [
        HumanMessage(content="F5E2 door won't lock"),
        HumanMessage(content="checked but still facing the issue"),
    ]
    q = _retrieval_query(messages)
    assert "F5E2" in q
    assert "door won't lock" in q
    assert "still facing" not in q


def test_retrieval_query_tried_but_did_not_solve_keeps_anchor() -> None:
    messages = [
        HumanMessage(content="door doesn't open"),
        HumanMessage(content="tried but did not solve the problem"),
    ]
    q = _retrieval_query(messages)
    assert "door" in q.lower()
    assert "did not solve" not in q.lower()


def test_retrieval_query_mid_cycle_correction_drops_vague_anchor() -> None:
    messages = [
        HumanMessage(content="doesn't wash properly"),
        HumanMessage(content="checked. those look good"),
        HumanMessage(content="actually wash stops halfway thru"),
    ]
    q = _retrieval_query(messages)
    assert "stops halfway" in q
    assert "doesn't wash properly" not in q
    assert "look good" not in q


def test_retrieval_query_stopping_halfway_drops_vague_anchor() -> None:
    messages = [
        HumanMessage(content="doesn't wash properly"),
        HumanMessage(content="checked those look good"),
        HumanMessage(content="actually wash was stopping halfway thru"),
    ]
    q = _retrieval_query(messages)
    assert "stopping halfway" in q
    assert "doesn't wash properly" not in q


def test_session_symptom_anchor_skips_acks() -> None:
    from repair_assistant.diagnostic.graph import _session_symptom_anchor

    messages = [
        HumanMessage(content="doesn't wash properly"),
        HumanMessage(content="no problem here"),
    ]
    assert _session_symptom_anchor(messages) == "doesn't wash properly"


def test_diagnose_turn_stream_closes_when_see_test_already_offered() -> None:
    from repair_assistant.qa.context import Citation

    llm = MagicMock()
    llm.model = "fake"
    llm.stream = MagicMock(side_effect=AssertionError("generate should not run"))
    state = _base_state()
    state["messages"] = [
        HumanMessage(content="Washer will not drain."),
        AIMessage(content="Proceed to TEST #8: Drain/Recirculation Pump [1]."),
        HumanMessage(content="checked all, no issues found there"),
    ]
    state["evidence_text"] = (
        "[1] Possible cause: Pump not pumping. See TEST #8: "
        "Drain/Recirculation Pump."
    )
    state["citations_available"] = [
        Citation(
            index=1,
            doc_id="tech-sheet-example",
            chunk_id="p10",
            label="W11320651 Rev B",
            page=10,
            excerpt="See TEST #8: Drain/Recirculation Pump.",
            block_text="See TEST #8: Drain/Recirculation Pump.",
        )
    ]
    state["retrieval_count"] = 1
    state["evidence_blocks"] = {1: "See TEST #8: Drain/Recirculation Pump."}
    db = MagicMock()
    manifest = MagicMock()
    with (
        patch("repair_assistant.diagnostic.graph.corpus_supports_appliance") as support,
        patch("repair_assistant.diagnostic.graph.search") as search,
    ):
        support.return_value = CorpusSupportResult(True, 1, "ok", "1 doc")
        events = list(
            diagnose_turn_stream(
                db,
                manifest,
                state,
                llm=llm,  # type: ignore[arg-type]
                classify_turn=lambda _s, _u: '{"label": "ack"}',
            )
        )
    search.assert_not_called()
    llm.stream.assert_not_called()
    done = events[-1]
    assert done["type"] == "done"
    assert done["abstained"] is False
    assert "no further grounded steps" in done["assistant_message"]
    assert done["diagnostic"]["phase"] == "close"
    assert any("test #8" in item.lower() for item in done["diagnostic"]["ruled_out"])
    assert done["tally"]["closed"] is True
    assert done["tally"]["symptom"] == "Washer will not drain."
    assert "See TEST #8" in done["tally"]["cleared"]
    assert done["tally"]["citation_index"] == 1


def test_orphan_ack_reply_not_abstain() -> None:
    from repair_assistant.diagnostic.graph import _maybe_orphan_ack_reply
    from repair_assistant.qa.acks import ORPHAN_ACK_IN_DIAGNOSE

    state = {
        "messages": [HumanMessage(content="no issues there")],
        "abstain_reason": "orphan_ack",
        "evidence_text": "",
    }
    reply = _maybe_orphan_ack_reply(state)  # type: ignore[arg-type]
    assert reply is not None
    assert reply["abstained"] is False
    assert ORPHAN_ACK_IN_DIAGNOSE in str(reply["messages"][0].content)
