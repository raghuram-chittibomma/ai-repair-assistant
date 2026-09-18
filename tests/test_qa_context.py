"""Unit tests for Phase 5 evidence formatting and citation parsing (no OpenAI)."""

from __future__ import annotations

from repair_assistant.qa.context import (
    EVIDENCE_BEGIN,
    EVIDENCE_END,
    FIGURE_UNREADABLE_NOTE,
    citations_from_answer,
    format_evidence,
    format_label,
    layout_from_hit,
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
    assert format_label(hit) == "W11320651 Rev A p.3 [structured] — F5E2"


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
    assert "[1] W11320651 Rev A p.3 [structured]" in text
    assert "modality: structured_text" in text
    assert "[2] kb-f5e2-front-load [structured]" in text
    assert len(citations) == 2
    assert citations[0].index == 1
    assert citations[1].doc_id == "kb-f5e2-front-load"


def test_format_evidence_notes_unread_figures() -> None:
    text, _ = format_evidence(
        [_hit(text="Check continuity at J36. See Figure 2 on the wiring diagram.")]
    )
    assert text.endswith(FIGURE_UNREADABLE_NOTE)
    assert EVIDENCE_END in text
    plain, _ = format_evidence([_hit()])
    assert FIGURE_UNREADABLE_NOTE not in plain


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


def test_layout_from_hit_requires_complete_bbox() -> None:
    ok = _hit(
        metadata={
            "bbox": {"x0": 10, "y0": 20, "x1": 200, "y1": 40},
            "page_width": 612,
            "page_height": 792,
        }
    )
    box, width, height = layout_from_hit(ok)
    assert box == {"x0": 10.0, "y0": 20.0, "x1": 200.0, "y1": 40.0}
    assert width == 612.0
    assert height == 792.0
    empty, _, _ = layout_from_hit(_hit(metadata={"bbox": {"x0": 1, "y0": 1, "x1": 0, "y1": 2}}))
    assert empty is None


def test_format_evidence_copies_table_row_bbox() -> None:
    _, citations = format_evidence(
        [
            _hit(
                metadata={
                    "bbox": {"x0": 8, "y0": 90, "x1": 400, "y1": 110},
                    "page_width": 612,
                    "page_height": 792,
                }
            )
        ]
    )
    assert citations[0].bbox["y0"] == 90
    assert citations[0].page_width == 612


def test_format_evidence_prefers_table_row_bbox_after_large_unit() -> None:
    """Stub-cost semantic units leave room for highlightable table rows (ADR-0051)."""
    unit = _hit(
        doc_id="installation-instructions-w11156977",
        chunk_id="008-installation-instructions-french",
        text="U" * 9_700,
        page=15,
        kind="semantic_unit",
        publication_number="W11156977",
        revision="D",
        unit_id=26,
        rep_kind=None,
        metadata={
            "page_start": 15,
            "page_end": 19,
            "unit_title": "French",
            "unit_key": "008-installation-instructions-french",
            "unit_type": "installation",
        },
    )
    prose = _hit(
        doc_id="use-and-care-w11156985",
        chunk_id="p23-prose",
        text="P" * 2_000,
        page=23,
        kind="prose",
        publication_number="W11156985",
        revision="A",
        metadata={},
    )
    row = _hit(
        doc_id="use-and-care-w11156985",
        chunk_id="p23-table_row-shipping",
        text="The shipping bolts are still in the back of the washer.",
        page=23,
        kind="table_row",
        publication_number="W11156985",
        revision="A",
        metadata={
            "bbox": {"x0": 154.0, "y0": 260.0, "x1": 577.0, "y1": 284.0},
            "page_width": 612.0,
            "page_height": 792.0,
        },
    )
    body, citations = format_evidence(
        [unit, prose, row],
        max_chars=10_200,
        semantic_attached_indexes={1},
    )
    assert "modality: semantic_pdf" in body
    assert "U" * 100 not in body, "stub must not dump the full extract"
    assert citations[0].block_text == unit.text.strip()
    chunk_ids = [c.chunk_id for c in citations]
    assert "008-installation-instructions-french" in chunk_ids
    assert "p23-table_row-shipping" in chunk_ids
    row_cite = next(c for c in citations if c.chunk_id == "p23-table_row-shipping")
    assert row_cite.bbox is not None
    assert row_cite.bbox["y0"] == 260.0
