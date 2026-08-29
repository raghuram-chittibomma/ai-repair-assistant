"""Figure-page classification (review R33) — synthetic text only."""

from __future__ import annotations

from repair_assistant.parsing.page_classify import (
    looks_like_figure_page,
    looks_like_matrix_page,
    should_index_chunk,
)


def test_wiring_diagram_title_with_sparse_ocr_is_figure() -> None:
    text = (
        "WIRING DIAGRAM\n"
        "h o ld  C y c le  S t a r t\n"
        "J 1  J 2  BK  W  R\n"
    )
    assert looks_like_figure_page(text)
    assert not should_index_chunk(text, "prose")


def test_spaced_control_panel_lettering_is_figure() -> None:
    text = "h o l d   C y c l e   S t a r t   P a u s e   L o c k"
    assert looks_like_figure_page(text)


def test_matrix_and_procedure_pages_are_not_figures() -> None:
    matrix = (
        "TROUBLESHOOTING GUIDE #2\n"
        + ("x" * 40)
        + "\nPROBLEM POSSIBLE CAUSE CHECKS & TESTS\n"
        + ("y" * 80)
    )
    assert looks_like_matrix_page(matrix)
    assert not looks_like_figure_page(matrix)
    procedure = (
        "TEST PROCEDURES\nTEST #1: ACU Power Check\n"
        "1. Unplug the washer.\n2. Check the ACU LED.\n"
        "3. Measure voltage at the connector.\n4. Reassemble and retest.\n"
    )
    assert not looks_like_figure_page(procedure)


def test_table_rows_stay_indexable() -> None:
    cell = "J36 | -1 | motor stator harness"
    assert should_index_chunk(cell, "table_row")
