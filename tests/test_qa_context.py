"""Unit tests for Phase 5 evidence formatting and citation parsing (no OpenAI)."""

from __future__ import annotations

from repair_assistant.qa.context import (
    EVIDENCE_BEGIN,
    EVIDENCE_END,
    citations_from_answer,
    format_evidence,
    format_label,
    resolve_citations,
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
    assert format_label(hit) == "W11320651 Rev A p.3 — F5E2"


def test_format_label_includes_matrix_group_and_problem() -> None:
    hit = _hit(
        text=(
            "[W11320651 Rev B] Table group: POOR WASH PERFORMANCE\n"
            "Problem: Oversuds. | Checks & tests: 1. Verify HE detergent."
        ),
        error_codes=[],
        page=11,
        revision="B",
    )
    label = format_label(hit)
    assert "p.11" in label
    assert "POOR WASH PERFORMANCE" in label
    assert "Oversuds" in label


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
            error_codes=["F5E2"],
        ),
    ]
    text, citations = format_evidence(hits)
    assert text.startswith(EVIDENCE_BEGIN)
    assert text.endswith(EVIDENCE_END)
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


def test_resolve_citations_falls_back_to_label_theme() -> None:
    hit = _hit(
        text=(
            "[W11320651 Rev B] Table group: POOR WASH PERFORMANCE\n"
            "Problem: Not cleaning clothes. | Checks & tests: 1. Verify load."
        ),
        error_codes=[],
        page=11,
        revision="B",
    )
    _, available = format_evidence([hit])
    answer = (
        'Checks from the "Not cleaning clothes" category:\n'
        "1. Verify that the load is not bunched.\n"
        "2. Ensure HE detergent."
    )
    cited = resolve_citations(answer, available)
    assert len(cited) == 1
    assert "Not cleaning clothes" in cited[0].label
    # Explicit [n] still wins over theme matching
    with_marker = resolve_citations(f"{answer} [1]", available)
    assert [c.index for c in with_marker] == [1]
