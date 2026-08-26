"""Unit tests for Phase 5 ask() with mock LLM (no Postgres / OpenAI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.corpus.support import ABSTAIN_NO_EVIDENCE
from repair_assistant.qa.generate import ask, build_user_prompt
from repair_assistant.retrieval.search import Hit, SearchResult


@dataclass
class FakeLLM:
    response: str

    def complete(self, system: str, user: str) -> str:
        return self.response


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
        text="F5E2: Lid switch fault.",
        page=1,
        kind="table_row",
        error_codes=["F5E2"],
        publication_number="W11320651",
        revision="A",
        score=0.95,
    )


def test_build_user_prompt_includes_appliance() -> None:
    prompt = build_user_prompt(
        "What is F5E2?",
        Appliance(model="WFW5620HW0", serial="CF81512345"),
        "[1] W11320651\nF5E2 text",
    )
    assert "Question: What is F5E2?" in prompt
    assert "WFW5620HW0" in prompt
    assert "CF81512345" in prompt
    assert "[1] W11320651" in prompt


@patch("repair_assistant.qa.generate.search")
def test_ask_abstains_when_no_hits(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="q", hits=[])
    db = MagicMock()
    result = ask(db, _manifest(), "What is F5E2?", llm=FakeLLM("unused"))
    assert result.abstained
    assert result.abstain_code == ABSTAIN_NO_EVIDENCE
    assert "manufacturer evidence" in result.answer.lower()


@patch("repair_assistant.qa.generate.search")
def test_ask_rejects_unknown_model_before_search(mock_search: MagicMock) -> None:
    db = MagicMock()
    result = ask(
        db,
        _manifest(),
        "doesn't turn on",
        appliance=Appliance(model="WTW4816FW0"),
        llm=FakeLLM("unused"),
    )
    assert result.abstained
    assert result.abstain_code == "unsupported_model"
    assert "Customer Care" in result.answer
    mock_search.assert_not_called()


@patch("repair_assistant.qa.generate.search")
def test_ask_returns_cited_answer(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="q", hits=[_hit()])
    db = MagicMock()
    llm = FakeLLM("F5E2 is a lid switch fault [1].")
    result = ask(
        db,
        _manifest(),
        "What is F5E2?",
        appliance=Appliance(model="WFW5620HW0"),
        llm=llm,
    )
    assert not result.abstained
    assert "[1]" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].doc_id == "tech-sheet-w11320651"


@patch("repair_assistant.qa.generate.search")
def test_ask_honours_llm_abstain(mock_search: MagicMock) -> None:
    mock_search.return_value = SearchResult(query="q", hits=[_hit()])
    db = MagicMock()
    llm = FakeLLM("ABSTAIN: Evidence does not describe this symptom.")
    result = ask(db, _manifest(), "Why is my washer purple?", llm=llm)
    assert result.abstained
    assert "does not describe" in result.abstain_reason
    assert result.citations == []
