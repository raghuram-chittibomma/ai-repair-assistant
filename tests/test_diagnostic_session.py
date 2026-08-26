"""Unit tests for Phase 6 diagnostic session (mock LLM / search)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.diagnostic.session import DiagnosticSession
from repair_assistant.retrieval.search import Hit, SearchResult


@dataclass
class FakeLLM:
    responses: list[str]
    calls: int = 0

    def complete(self, system: str, user: str) -> str:
        out = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return out


def _manifest() -> Manifest:
    doc = Document(
        data={
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech sheet",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
        path=Path("tech-sheet-w11320651.yaml"),
    )
    return Manifest(documents=[doc])


def _hit() -> Hit:
    return Hit(
        doc_id="tech-sheet-w11320651",
        chunk_id="p1-r1",
        text="F5E2: Door lock failure when ACU cannot confirm locked state.",
        page=1,
        kind="table_row",
        error_codes=["F5E2"],
        publication_number="W11320651",
        revision="A",
        score=0.95,
    )


@patch("repair_assistant.diagnostic.graph.search")
def test_diagnostic_session_single_turn(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="F5E2", hits=[_hit()])
    db = MagicMock()
    llm = FakeLLM(["F5E2 indicates a door lock fault [1]."])
    session = DiagnosticSession(
        _manifest(),
        appliance=Appliance(model="WFW5620HW0"),
        llm=llm,
    )
    result = session.send(db, "What does F5E2 mean?")
    assert result.turn == 1
    assert not result.abstained
    assert "F5E2" in result.assistant_message
    assert len(result.citations) == 1
    assert session.turn_count == 1


@patch("repair_assistant.diagnostic.graph.search")
def test_diagnostic_session_multi_turn_accumulates(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="q", hits=[_hit()])
    db = MagicMock()
    llm = FakeLLM(
        [
            "F5E2 is a door lock fault [1]. Does the door appear fully closed?",
            "Check the door lock wiring harness next [1].",
        ]
    )
    session = DiagnosticSession(
        _manifest(),
        appliance=Appliance(model="WFW5620HW0"),
        llm=llm,
    )
    first = session.send(db, "Washer shows F5E2")
    second = session.send(db, "Door looks closed")
    assert first.turn == 1
    assert second.turn == 2
    assert llm.calls == 2
    assert "harness" in second.assistant_message.lower()


@patch("repair_assistant.diagnostic.graph.search")
def test_diagnostic_session_blocks_bypass_without_retrieval(mock_search: MagicMock) -> None:
    db = MagicMock()
    session = DiagnosticSession(
        _manifest(),
        appliance=Appliance(model="WFW5620HW0"),
        llm=FakeLLM(["unused"]),
    )
    result = session.send(db, "How do I bypass the door lock?")
    assert result.abstained
    assert result.escalated
    assert result.safety_action == "block"
    mock_search.assert_not_called()


@patch("repair_assistant.diagnostic.graph.search")
def test_diagnostic_session_abstains_without_hits(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="q", hits=[])
    db = MagicMock()
    session = DiagnosticSession(
        _manifest(),
        appliance=Appliance(model="WFW5620HW0"),
        llm=FakeLLM(["unused"]),
    )
    result = session.send(db, "What is ZZ99?")
    assert result.abstained
    assert "manufacturer evidence" in result.assistant_message.lower()
