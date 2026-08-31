"""Layout-pack scorer (synthetic chunks, no PDF)."""

from __future__ import annotations

from repair_assistant.parsing.layout_pack import score_page, scorecard_markdown


def test_score_page_phrase_and_section() -> None:
    spec = {
        "id": "fault-chart-2-14",
        "pdf_page": 32,
        "printed": "2-14",
        "class": "table_heavy",
        "asserts": [
            {"type": "phrase_present", "phrases": ["F6E1", "TEST #2"]},
            {"type": "min_table_rows", "min": 1},
            {"type": "section_not_like", "pattern": "WARNING"},
        ],
    }
    chunks = [
        {
            "page": 32,
            "kind": "table_row",
            "text": "F6E1 Communication Error See TEST #2",
            "metadata": {"body_text": "F6E1 | TEST #2", "section_path": ["Fault/Error Code Chart"]},
        }
    ]
    result = score_page(spec, chunks)
    assert result.passed
    assert result.pdf_page == 32


def test_scorecard_markdown_counts_fails() -> None:
    spec = {
        "id": "wiring",
        "pdf_page": 41,
        "printed": "3-3",
        "class": "schematic",
        "asserts": [{"type": "max_prose_chunks", "max": 0}],
    }
    chunks = [
        {
            "page": 41,
            "kind": "prose",
            "text": "letter salad",
            "metadata": {"body_text": "letter salad", "section_path": []},
        }
    ]
    result = score_page(spec, chunks)
    assert not result.passed
    card = scorecard_markdown([result])
    assert "FAIL" in card
    assert "wiring" in card
