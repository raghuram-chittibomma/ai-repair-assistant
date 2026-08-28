"""Tests for hierarchical troubleshooting table context."""

from repair_assistant.parsing.chunker import chunk_document
from repair_assistant.parsing.models import ExtractedDocument, ExtractedPage, Table, TableRow
from repair_assistant.parsing.table_context import (
    detect_column_map,
    detect_matrix_kind,
    is_group_header_row,
    is_problem_anchor,
    is_troubleshooting_matrix,
    iter_contextual_rows,
    parse_troubleshooting_prose,
)


def test_is_troubleshooting_matrix():
    assert is_troubleshooting_matrix(["Problem", "Possible cause", "Checks & tests"])
    assert not is_troubleshooting_matrix(["Error Code", "Problem", "Checks & Tests"])


def test_group_header_row_detection():
    col = detect_column_map(["Problem", "Possible cause", "Checks & tests"])
    assert is_group_header_row(
        ["POOR WASH PERFORMANCE", "Please refer Use & Care Guide.", ""],
        col,
    )
    assert not is_group_header_row(
        ["Oversuds.", "", "1. Verify use of HE detergent."],
        col,
    )


def test_iter_contextual_rows_carries_group():
    table = Table(
        headers=["Problem", "Possible cause", "Checks & tests"],
        rows=[
            TableRow(
                cells=["POOR WASH PERFORMANCE", "Please refer Use & Care Guide.", ""],
                page=11,
            ),
            TableRow(
                cells=[
                    "Oversuds.",
                    "",
                    "1. Verify use of HE detergent. 2. Excessive detergent usage.",
                ],
                page=11,
            ),
            TableRow(
                cells=["Load not rinsed.", "", "1. Check proper water supply."],
                page=11,
            ),
        ],
        page=11,
    )
    rows = iter_contextual_rows(table)
    data = [r for r in rows if r.role == "data"]
    assert len(data) == 2
    assert data[0].group_title == "POOR WASH PERFORMANCE"
    assert "Use & Care" in data[0].group_note
    assert data[0].cells[0] == "Oversuds."
    assert data[1].group_title == "POOR WASH PERFORMANCE"


def test_chunker_emits_one_chunk_per_matrix_row():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=11,
                text="FOR SERVICE TECHNICIAN'S USE ONLY\nTROUBLESHOOTING GUIDE #2",
                tables=[
                    Table(
                        headers=["Problem", "Possible cause", "Checks & tests"],
                        rows=[
                            TableRow(
                                cells=[
                                    "POOR WASH PERFORMANCE",
                                    "Please refer Use & Care Guide.",
                                    "",
                                ],
                                page=11,
                            ),
                            TableRow(
                                cells=[
                                    "Oversuds.",
                                    "",
                                    "1. Verify use of HE detergent.",
                                ],
                                page=11,
                            ),
                            TableRow(
                                cells=[
                                    "Load not rinsed.",
                                    "",
                                    "4. See TEST #6: Water Inlet Valves, page 16.",
                                ],
                                page=11,
                            ),
                        ],
                        page=11,
                    )
                ],
            )
        ],
    )
    chunks = chunk_document(
        document,
        strategy="structured",
        doc_id="tech-sheet-w11320651",
        publication_number="W11320651",
        revision="B",
        doc_title="Tech Sheet",
        doc_type="tech_sheet",
    )
    matrix_rows = [
        c
        for c in chunks
        if c.kind == "table_row" and c.metadata.get("matrix_type") == "troubleshooting"
    ]
    assert len(matrix_rows) == 2
    oversuds = next(c for c in matrix_rows if "Oversuds" in c.text)
    assert "Table group: POOR WASH PERFORMANCE" in oversuds.text
    assert "Group note:" in oversuds.text and "Use & Care" in oversuds.text
    assert oversuds.metadata.get("table_group") == "POOR WASH PERFORMANCE"
    rinsed = next(c for c in matrix_rows if "Load not rinsed" in c.text)
    assert "TEST #6" in rinsed.text
    assert len([c for c in chunks if c.kind == "heading" and len(c.text) > 2000]) == 0


def test_prose_fallback_splits_troubleshooting_guide():
    prose = (
        "FOR SERVICE TECHNICIAN'S USE ONLY\n"
        "TROUBLESHOOTING GUIDE #2\n"
        "PROBLEM POSSIBLE CAUSE CHECKS & TESTS\n"
        "POOR WASH PERFORMANCE\n"
        "Please refer Use & Care Guide.\n"
        "Oversuds. 1. Verify use of HE detergent. 2. Excessive detergent usage.\n"
        "Load not rinsed. 1. Check proper water supply. 2. Not using HE detergent.\n"
        "Not cleaning clothes. 1. Verify that load is not bunched.\n"
    )
    rows = parse_troubleshooting_prose(prose)
    assert len(rows) >= 2
    assert any("Oversuds" in r.cells[0] for r in rows)
    assert all(r.group_title == "POOR WASH PERFORMANCE" for r in rows)


def test_prose_fallback_ltr_interleaved_matrix():
    """Real pdfplumber LTR shape: group prefix glued to symptom, PERFORMANCE next line."""
    prose = (
        "FOR SERVICE TECHNICIAN'S USE ONLY\n"
        "TROUBLESHOOTING GUIDE #2\n"
        "PROBLEM POSSIBLE CAUSE\n"
        "POOR WASH Oversuds. 1. Verify use of HE detergent.\n"
        "PERFORMANCE 2. Excessive detergent usage.\n"
        "Please refer 3. Check drain hose and filter for obstructions.\n"
        "Use & Care Guide. Incorrect water level. See \"WON'T FILL\", page 10.\n"
        "Clothes wet after cycle is complete. 1. Single or tangled items.\n"
        "Load not rinsed. 1. Check proper water supply.\n"
        "Not cleaning clothes. 1. Verify that load is not bunched.\n"
        "POOR DRY Dry heater not working. See TEST #9b.\n"
        "PERFORMANCE Dry sensor not working.\n"
    )
    rows = parse_troubleshooting_prose(prose)
    poor = [r for r in rows if "POOR WASH" in (r.group_title or "")]
    assert len(poor) >= 3
    assert any(r.cells[0].startswith("Oversuds") for r in poor)
    assert any("rinsed" in r.cells[0].lower() for r in poor)
    assert any("cleaning" in r.cells[0].lower() for r in poor)
    oversuds = next(r for r in poor if "Oversuds" in r.cells[0])
    assert "HE detergent" in oversuds.cells[2]


def test_matrix_page_not_column_reordered():
    from repair_assistant.parsing.page_classify import looks_like_matrix_page

    text = (
        "TROUBLESHOOTING GUIDE #2\n"
        "PROBLEM POSSIBLE CAUSE\n"
        "POOR WASH PERFORMANCE\n"
        "Oversuds. 1. Verify HE detergent.\n"
    )
    assert looks_like_matrix_page(text)


def test_chunker_prose_fallback_not_one_mega_chunk():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=11,
                text=(
                    "FOR SERVICE TECHNICIAN'S USE ONLY\n"
                    "TROUBLESHOOTING GUIDE #2\n"
                    "PROBLEM POSSIBLE CAUSE CHECKS & TESTS\n"
                    "POOR WASH PERFORMANCE\n"
                    "Please refer Use & Care Guide.\n"
                    "Oversuds. 1. Verify use of HE detergent.\n"
                    "Load not rinsed. 1. Check proper water supply.\n"
                ),
            )
        ],
    )
    chunks = chunk_document(
        document,
        strategy="structured",
        publication_number="W11320651",
        doc_type="tech_sheet",
    )
    matrix_rows = [c for c in chunks if c.metadata.get("matrix_type") == "troubleshooting"]
    assert len(matrix_rows) >= 1
    assert not any(c.kind == "heading" and len(c.text) > 1500 for c in chunks)


def test_is_problem_anchor_guide1():
    assert is_problem_anchor("WON'T POWER UP")
    assert is_problem_anchor("WON'T START CYCLE")
    assert not is_problem_anchor("POOR WASH PERFORMANCE")
    assert not is_problem_anchor("Oversuds.")


def test_detect_matrix_kind_guide1():
    table = Table(
        headers=["Problem", "Possible cause", "Checks & tests"],
        rows=[
            TableRow(
                cells=[
                    "WON'T POWER UP\n• No operation\n• No keypad response",
                    "Control lock is activated.",
                    "Check if the control lock LED is on.",
                ],
                page=10,
            ),
            TableRow(
                cells=[
                    "",
                    "No power to washer.",
                    "Check power at outlet, check circuit breakers.",
                ],
                page=10,
            ),
            TableRow(
                cells=[
                    "",
                    "ACU problem.",
                    "See TEST #1: ACU Power Check, page 12.",
                ],
                page=10,
            ),
        ],
        page=10,
    )
    assert detect_matrix_kind(table) == "problem_spanned"


def test_iter_contextual_rows_carries_problem_guide1():
    table = Table(
        headers=["Problem", "Possible cause", "Checks & tests"],
        rows=[
            TableRow(
                cells=[
                    "WON'T POWER UP\n• No operation\n• No keypad response",
                    "Control lock is activated.",
                    "Check if the control lock LED is on.",
                ],
                page=10,
            ),
            TableRow(
                cells=[
                    "",
                    "No power to washer.",
                    "Check power at outlet, check circuit breakers.",
                ],
                page=10,
            ),
            TableRow(
                cells=[
                    "",
                    "ACU problem.",
                    "See TEST #1: ACU Power Check, page 12.",
                ],
                page=10,
            ),
        ],
        page=10,
    )
    rows = iter_contextual_rows(
        table, guide_title="TROUBLESHOOTING GUIDE #1"
    )
    data = [r for r in rows if r.role == "data"]
    assert len(data) == 3
    assert all(r.problem_title == "WON'T POWER UP" for r in data)
    assert all(r.matrix_kind == "problem_spanned" for r in data)
    assert all(r.guide_title == "TROUBLESHOOTING GUIDE #1" for r in data)
    assert "No operation" in data[0].problem_detail
    assert data[1].cells[1] == "No power to washer."
    assert "TEST #1" in data[2].cells[2]


def test_chunker_emits_one_chunk_per_guide1_cause_row():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=10,
                text=(
                    "FOR SERVICE TECHNICIAN'S USE ONLY\n"
                    "TROUBLESHOOTING GUIDE #1\n"
                    "PROBLEM POSSIBLE CAUSE CHECKS & TESTS"
                ),
                tables=[
                    Table(
                        headers=["Problem", "Possible cause", "Checks & tests"],
                        rows=[
                            TableRow(
                                cells=[
                                    "WON'T POWER UP\n• No operation\n• No LEDs or display",
                                    "Control lock is activated.",
                                    "Check if the control lock LED is on.",
                                ],
                                page=10,
                            ),
                            TableRow(
                                cells=[
                                    "",
                                    "No power to washer.",
                                    "Check power at outlet.",
                                ],
                                page=10,
                            ),
                            TableRow(
                                cells=[
                                    "",
                                    "ACU problem.",
                                    "See TEST #1: ACU Power Check, page 12.",
                                ],
                                page=10,
                            ),
                        ],
                        page=10,
                    )
                ],
            )
        ],
    )
    chunks = chunk_document(
        document,
        strategy="structured",
        doc_id="tech-sheet-w11320651",
        publication_number="W11320651",
        revision="B",
        doc_title="Tech Sheet",
        doc_type="tech_sheet",
    )
    matrix_rows = [
        c
        for c in chunks
        if c.kind == "table_row" and c.metadata.get("matrix_type") == "troubleshooting"
    ]
    assert len(matrix_rows) == 3
    lock = next(c for c in matrix_rows if "Control lock" in c.text)
    assert "Guide: TROUBLESHOOTING GUIDE #1" in lock.text
    assert "Problem: WON'T POWER UP" in lock.text
    assert lock.metadata.get("matrix_kind") == "problem_spanned"
    assert lock.metadata.get("problem_title") == "WON'T POWER UP"
    power = next(c for c in matrix_rows if "No power to washer" in c.text)
    assert power.metadata.get("problem_title") == "WON'T POWER UP"
    acu = next(c for c in matrix_rows if "ACU problem" in c.text)
    assert "TEST #1" in acu.text
