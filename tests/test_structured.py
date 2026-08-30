"""Structured claim→evidence binding (ADR-0028). No OpenAI."""

from __future__ import annotations

from repair_assistant.qa.context import Citation
from repair_assistant.qa.structured import (
    bind_generation,
    citations_from_claims,
    parse_model_output,
)


def _cite(index: int, doc_id: str = "tech-sheet") -> Citation:
    return Citation(
        index=index,
        doc_id=doc_id,
        chunk_id=f"c{index}",
        label=f"W11320651 p.{index}",
        page=index,
        excerpt="excerpt",
    )


def test_parse_json_claims() -> None:
    raw = """
    {"abstained": false, "abstain_reason": "",
     "answer": "F5E2 is a door lock fault [1].",
     "claims": [{"text": "F5E2 is a door lock fault", "evidence_index": 1}]}
    """
    parsed = parse_model_output(raw)
    assert not parsed.abstained
    assert parsed.claims[0].evidence_index == 1
    available = [_cite(1), _cite(2, "other")]
    cited = citations_from_claims(parsed.claims, available)
    assert [c.doc_id for c in cited] == ["tech-sheet"]


def test_parse_binds_without_bracket_markers() -> None:
    raw = """
    {"abstained": false, "abstain_reason": "",
     "answer": "Per the service manual the door lock failed.",
     "claims": [{"text": "the door lock failed", "evidence_index": 1}]}
    """
    bound = bind_generation(raw, [_cite(1)])
    assert not bound.abstained
    assert "[1]" not in bound.display
    assert bound.citations[0].doc_id == "tech-sheet"


def test_parse_abstain_json() -> None:
    raw = '{"abstained": true, "abstain_reason": "no matching row", "answer": "", "claims": []}'
    bound = bind_generation(raw, [_cite(1)])
    assert bound.abstained
    assert bound.display.startswith("ABSTAIN:")
    assert "no matching row" in bound.abstain_reason
    assert bound.citations == []


def test_parse_legacy_abstain_and_prose() -> None:
    abstain = parse_model_output("ABSTAIN: Evidence does not describe this symptom.")
    assert abstain.abstained
    prose = bind_generation("F5E2 is a lid switch fault [1].", [_cite(1)])
    assert not prose.abstained
    assert prose.citations[0].index == 1


def test_parse_keeps_optional_diagnostic() -> None:
    raw = """
    {"abstained": false, "abstain_reason": "",
     "answer": "Check the latch [1].",
     "claims": [{"text": "Check the latch", "evidence_index": 1}],
     "diagnostic": {"phase": "next_step", "hypotheses": ["latch"],
      "ruled_out": [], "observations": [], "next_check": "TEST #4"}}
    """
    parsed = parse_model_output(raw)
    assert parsed.diagnostic is not None
    assert parsed.diagnostic["phase"] == "next_step"
    assert parsed.diagnostic["next_check"] == "TEST #4"


def test_invalid_evidence_index_is_dropped() -> None:
    raw = '{"abstained": false, "abstain_reason": "", "answer": "x", "claims": [{"text": "x", "evidence_index": 99}]}'
    bound = bind_generation(raw, [_cite(1)])
    assert bound.citations == []
