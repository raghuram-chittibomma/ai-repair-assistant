"""Tests for hybrid parse architecture (ADR-0024)."""

from pathlib import Path

from repair_assistant.parsing.canonical import build_canonical
from repair_assistant.parsing.models import ExtractedDocument, ExtractedPage, Table, TableRow
from repair_assistant.parsing.page_classify import looks_like_matrix_page
from repair_assistant.parsing.parse_quality import (
    audit_page,
    clear_quality_override_cache,
    infer_contiguous_steps,
    numbered_steps_present,
    phrase_order_monotonic,
    quality_override_for,
)


def test_phrase_order_monotonic():
    good = "AAA\nBBB\nCCC"
    assert phrase_order_monotonic(good, ["AAA", "BBB", "CCC"])
    bad = "BBB before AAA: BBB ... AAA"
    assert not phrase_order_monotonic(bad, ["AAA", "BBB"])


def test_numbered_steps_present():
    text = "1. first\n8. last\n9. nine\n10. ten"
    assert numbered_steps_present(text, [1, 8, 9, 10]) == []
    assert numbered_steps_present(text, [1, 2, 3]) == [2, 3]


def test_infer_contiguous_steps():
    text = "\n".join(f"{n}. step" for n in (1, 2, 3, 4, 5, 8))
    assert infer_contiguous_steps(text) == list(range(1, 9))
    assert infer_contiguous_steps("1. only") is None


def test_audit_flags_multi_column_pdfplumber():
    audit = audit_page(
        page=12,
        text="step 9 before step 1",
        tables=[],
        layout_kind="multi_column",
        prose_source="pdfplumber",
    )
    assert "reading_order_suspect" in audit.flags


def test_quality_override_from_config_not_absolute_page():
    clear_quality_override_cache()
    hit = quality_override_for(Path("corpus/documents/W11320651B.pdf"), 12)
    assert hit is not None
    assert "TEST PROCEDURES" in hit.phrase_markers
    assert 9 in hit.expect_steps
    # Same absolute page on an unrelated PDF must not inherit the override.
    miss = quality_override_for(Path("corpus/documents/other-manual.pdf"), 12)
    assert miss is None


def test_matrix_detection_is_content_based():
    matrix = (
        "TROUBLESHOOTING GUIDE #2\n"
        + ("x" * 40)
        + "\nPROBLEM POSSIBLE CAUSE CHECKS & TESTS\n"
        + ("y" * 80)
    )
    assert looks_like_matrix_page(matrix)
    assert not looks_like_matrix_page("TEST PROCEDURES\nTEST #1: ACU Power Check")


def test_build_canonical_tree():
    doc = ExtractedDocument(
        path="synthetic",
        extractor="hybrid",
        pages=[
            ExtractedPage(
                number=12,
                text="TEST PROCEDURES\nTEST #1: ACU Power Check\n1. Step one.",
                tables=[
                    Table(
                        headers=["Pin", "Value"],
                        rows=[TableRow(cells=["J8", "800"], page=12)],
                        page=12,
                    )
                ],
            )
        ],
    )
    canonical = build_canonical(doc)
    assert canonical.extractor == "hybrid"
    assert len(canonical.nodes) == 1
    kinds = {c.kind for c in canonical.nodes[0].children}
    assert "table" in kinds


def test_hybrid_extractor_registered():
    from repair_assistant.parsing.extractors import get_extractor

    ext = get_extractor("hybrid")
    assert ext.name == "hybrid"


def test_default_extractor_is_hybrid():
    from repair_assistant.parsing.write import DEFAULT_EXTRACTOR

    assert DEFAULT_EXTRACTOR == "hybrid"
