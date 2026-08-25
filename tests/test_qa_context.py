"""Unit tests for Phase 5 evidence formatting and citation parsing (no OpenAI)."""

from __future__ import annotations

from repair_assistant.qa.context import (
    citations_from_answer,
    format_evidence,
    format_label,
)
from repair_assistant.retrieval.search import Hit


def _hit(**kwargs) -> Hit:
    defaults = {
        "doc_id": "tech-sheet-w11320651",
        "chunk_id": "p3-r12",
        "text": "F5E2 indicates the main control cannot detect the lid is closed.",
        "page": 3,
        "kind": "table_row",
        "error_codes": ["F5E2"],
        "publication_number": "W11320651",
        "revision": "A",
        "score": 0.91,
    }
    defaults.update(kwargs)
    return Hit(**defaults)


def test_format_label_includes_revision_and_page() -> None:
    hit = _hit()
    assert format_label(hit) == "W11320651 Rev A p.3"


def test_format_evidence_numbers_blocks_and_truncates() -> None:
    hits = [
        _hit(chunk_id="a", text="First chunk text."),
        _hit(
            chunk_id="b",
            doc_id="kb-f5e2-front-load",
            publication_number=None,
            revision=None,
            page=None,
            text="Second chunk about F5 E2 lid switch.",
        ),
    ]
    text, citations = format_evidence(hits)
    assert "[1] W11320651 Rev A p.3" in text
    assert "[2] kb-f5e2-front-load" in text
    assert len(citations) == 2
    assert citations[0].index == 1
    assert citations[1].doc_id == "kb-f5e2-front-load"


def test_citations_from_answer_deduplicates_and_preserves_order() -> None:
    _, available = format_evidence([_hit(), _hit(chunk_id="b", page=4)])
    answer = "The lid switch may be faulty [2]. See also [1] and [2]."
    cited = citations_from_answer(answer, available)
    assert [c.index for c in cited] == [2, 1]
    assert cited[0].chunk_id == "b"
