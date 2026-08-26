"""Unit tests for ask_stream (no live OpenAI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from repair_assistant.qa.generate import ask_stream
from repair_assistant.retrieval.search import Hit, SearchResult
from repair_assistant.safety.models import Audience, SafetyAction


class FakeStreamLLM:
    model = "fake"

    def stream(self, system: str, user: str):
        yield "Door "
        yield "lock "
        yield "failure [1]."


def test_ask_stream_emits_status_tokens_done():
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
        patch("repair_assistant.qa.generate.assess_request") as assess,
        patch("repair_assistant.qa.generate.search") as search,
        patch("repair_assistant.qa.generate.gate_answer") as gate,
    ):
        assess.return_value = MagicMock(
            action=SafetyAction.ALLOW,
            reason="",
            prompt_directive="",
        )
        search.return_value = SearchResult(query="F5E2", hits=hits, fetched=1, filtered_out=0)
        gated = MagicMock()
        gated.text = "Door lock failure [1]."
        gated.blocked = False
        gated.notice = ""
        gated.action = SafetyAction.ALLOW
        gated.escalated = False
        gate.return_value = gated

        events = list(
            ask_stream(
                db,
                manifest,
                "What is F5E2?",
                audience=Audience.OWNER,
                llm=FakeStreamLLM(),  # type: ignore[arg-type]
            )
        )

    types = [e["type"] for e in events]
    assert types[0] == "status"
    assert events[0]["phase"] == "retrieving"
    assert types.count("token") == 3
    assert types[-1] == "done"
    assert events[-1]["answer"] == "Door lock failure [1]."
    assert events[-1]["abstained"] is False
