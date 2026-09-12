"""Prose word-span bbox matching (ADR-0038) — no live PDF."""

from __future__ import annotations

from repair_assistant.parsing.chunker import chunk_document
from repair_assistant.parsing.models import (
    BBox,
    ExtractedDocument,
    ExtractedPage,
    Table,
    TableRow,
    Word,
)
from repair_assistant.parsing.prose_bbox import (
    attach_prose_layout,
    attach_table_row_prose_layout,
    match_span_bbox,
    span_layout_metadata,
    words_from_pdfplumber,
)

SENTENCE = (
    "Disconnect power before servicing the washer drain pump filter housing assembly."
)


def _words(
    text: str,
    *,
    x0: float = 50.0,
    y0: float = 100.0,
    width: float = 16.0,
    height: float = 10.0,
    gap: float = 4.0,
) -> list[Word]:
    out: list[Word] = []
    x = x0
    for token in text.split():
        token_w = width * max(1, len(token) / 4)
        out.append(Word(text=token, x0=x, y0=y0, x1=x + token_w, y1=y0 + height))
        x += token_w + gap
    return out


def test_unique_span_gets_bbox() -> None:
    words = _words(SENTENCE)
    box = match_span_bbox(SENTENCE, words, 612.0, 792.0)
    assert box == BBox(
        x0=words[0].x0,
        y0=words[0].y0,
        x1=words[-1].x1,
        y1=words[-1].y1,
    )
    meta = span_layout_metadata(box, 612.0, 792.0)
    assert meta["bbox_space"] == "pdfplumber_pt"
    assert meta["page_width"] == 612.0


def test_duplicate_warning_gets_no_bbox() -> None:
    words = _words(SENTENCE) + _words(SENTENCE, x0=50.0, y0=200.0)
    assert match_span_bbox(SENTENCE, words, 612.0, 792.0) is None


def test_two_column_smear_refused() -> None:
    tokens = SENTENCE.split()
    mid = len(tokens) // 2
    left = _words(" ".join(tokens[:mid]), x0=50.0, y0=100.0)
    right = _words(" ".join(tokens[mid:]), x0=400.0, y0=100.0)
    assert match_span_bbox(SENTENCE, left + right, 612.0, 792.0) is None


def test_too_short_refused() -> None:
    words = _words("WARNING WARNING WARNING")
    assert match_span_bbox("WARNING", words, 612.0, 792.0) is None


def test_figure_page_skipped() -> None:
    words = _words(SENTENCE)
    assert (
        match_span_bbox(SENTENCE, words, 612.0, 792.0, layout_kind="figure") is None
    )
    assert (
        match_span_bbox(SENTENCE, words, 612.0, 792.0, layout_kind="schematic")
        is None
    )


def test_table_row_prose_boxes_short_unique_cause() -> None:
    cause = "Reset washer."
    checks = "Unplug and reconnect the power cord."
    page = ExtractedPage(
        number=10,
        text=f"DOOR WON'T UNLOCK {cause} {checks}",
        layout_kind="matrix",
        page_width=396.0,
        page_height=612.0,
        words=_words("DOOR WON'T UNLOCK")
        + _words(cause, x0=140.0, y0=200.0)
        + _words(checks, x0=220.0, y0=200.0),
    )
    meta: dict = {}
    attach_table_row_prose_layout(meta, page, cause=cause, checks=checks, body="")
    assert meta["bbox"]["y0"] == 200.0
    assert meta["page_width"] == 396.0
    assert meta["bbox"]["x0"] == 140.0


def test_attach_prose_layout_writes_metadata() -> None:
    page = ExtractedPage(
        number=4,
        text=SENTENCE,
        layout_kind="procedure",
        page_width=612.0,
        page_height=792.0,
        words=_words(SENTENCE),
    )
    meta: dict = {}
    attach_prose_layout(meta, page, SENTENCE)
    assert meta["bbox"]["x0"] == page.words[0].x0
    assert meta["bbox_space"] == "pdfplumber_pt"


def test_table_row_bbox_unchanged() -> None:
    row = TableRow(
        cells=["F5E2", "Door lock"],
        page=8,
        bbox=BBox(10, 80, 400, 100),
    )
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=8,
                text=SENTENCE,
                layout_kind="matrix",
                page_width=612.0,
                page_height=792.0,
                words=_words(SENTENCE, y0=200.0),
                tables=[
                    Table(
                        headers=["Error Code", "Problem"],
                        rows=[row],
                        page=8,
                        page_width=612,
                        page_height=792,
                    )
                ],
            )
        ],
    )
    chunks = chunk_document(document, strategy="structured")
    rows = [c for c in chunks if c.kind == "table_row"]
    prose = [c for c in chunks if c.kind in {"prose", "procedure", "heading"}]
    assert rows[0].metadata["bbox"] == {"x0": 10, "y0": 80, "x1": 400, "y1": 100}
    assert any(c.metadata.get("bbox") for c in prose)


def test_words_from_pdfplumber_skips_bad_entries() -> None:
    class _Page:
        def extract_words(self):
            return [
                {"text": "ok", "x0": 1, "y0": 2, "x1": 8, "y1": 10},
                {
                    "text": "pdf",
                    "x0": 10,
                    "x1": 20,
                    "top": 30,
                    "bottom": 40,
                },
                {"text": "bad"},
                "skip",
            ]

    words = words_from_pdfplumber(_Page())
    assert [w.text for w in words] == ["ok", "pdf"]
    assert words[1].y0 == 30
    assert words[1].y1 == 40
