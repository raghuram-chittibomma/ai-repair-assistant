"""Synthetic-document tests for extract/chunk interfaces."""

from pathlib import Path

import pytest

from repair_assistant.parsing.chunker import chunk_document
from repair_assistant.parsing.extractors import PypdfExtractor
from repair_assistant.parsing.models import (
    ExtractedDocument,
    ExtractedPage,
    Table,
    TableRow,
)

pikepdf = pytest.importorskip("pikepdf")


def _pdf_with_text(path: Path, text: str) -> Path:
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    # Keep the content stream simple; escape parentheses lightly.
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    page.contents_add(pikepdf.Stream(pdf, f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode()))
    pdf.save(str(path))
    return path


def test_pypdf_extractor_returns_pages(tmp_path):
    path = _pdf_with_text(tmp_path / "sample.pdf", "F8E1 Valve failure")
    doc = PypdfExtractor().extract(path)
    assert doc.extractor == "pypdf"
    assert len(doc.pages) == 1
    assert "F8E1" in doc.pages[0].text


def test_structured_chunker_binds_error_code_from_table_row():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=8,
                text="ERROR CODE DISPLAY\nSee table below.",
                tables=[
                    Table(
                        headers=["Error Code", "Problem", "Checks & Tests"],
                        rows=[
                            TableRow(
                                cells=[
                                    "F6E1",
                                    "No communication from the HMI detected by ACU.",
                                    "See Test #2: Human-Machine Interface (HMI), page 14.",
                                ],
                                page=8,
                            )
                        ],
                        page=8,
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
    )
    table_chunks = [c for c in chunks if c.kind == "table_row"]
    assert table_chunks
    assert table_chunks[0].error_codes == ["F6E1"]
    assert "No communication from the HMI" in table_chunks[0].text
    assert "Test #2" in table_chunks[0].text
    assert "Error Code:" in table_chunks[0].text
    assert "W11320651" in table_chunks[0].text
    assert "ERROR CODE DISPLAY" in table_chunks[0].text or "Section:" in table_chunks[0].text
    assert table_chunks[0].metadata.get("body_text")
    assert table_chunks[0].metadata.get("headers") == [
        "Error Code",
        "Problem",
        "Checks & Tests",
    ]


def test_numeric_table_row_includes_column_headers():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=20,
                text="THERMISTOR\nResistance chart",
                tables=[
                    Table(
                        headers=["Temp F", "Temp C", "Resistance kOhm"],
                        rows=[
                            TableRow(cells=["70", "21", "3.4"], page=20),
                            TableRow(cells=["14", "-10", "111.6"], page=20),
                        ],
                        page=20,
                    )
                ],
            )
        ],
    )
    chunks = chunk_document(
        document,
        strategy="structured",
        publication_number="W11169652",
        revision="B",
    )
    rows = [c for c in chunks if c.kind == "table_row"]
    assert len(rows) == 2
    assert "Temp F: 70" in rows[0].text
    assert "Resistance kOhm: 3.4" in rows[0].text
    assert "14" in rows[1].text
    assert "Temp F" in rows[1].text
    # Must not be bare digits-only for embedding.
    assert any(ch.isalpha() for ch in rows[1].text)


def test_section_inherited_on_prose_under_heading():
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=4,
                text=(
                    "TEST #4 DRAIN SYSTEM\n"
                    "Check the drain pump for blockage.\n"
                    "Verify the hose is clear."
                ),
            )
        ],
    )
    chunks = chunk_document(
        document,
        strategy="structured",
        publication_number="W11320651",
    )
    prose = [c for c in chunks if c.kind in {"prose", "procedure", "heading"}]
    assert prose
    # Heading-aware split keeps heading with body, or inherits on following pieces.
    joined = "\n".join(c.text for c in prose)
    assert "TEST #4" in joined
    assert "drain pump" in joined.lower() or "DRAIN" in joined
    assert any(c.metadata.get("section_path") for c in prose)


def test_structured_chunker_skips_figure_prose_keeps_tables() -> None:
    document = ExtractedDocument(
        path="synthetic",
        extractor="test",
        pages=[
            ExtractedPage(
                number=26,
                text="WIRING DIAGRAM\nh o ld  C y c le  S t a r t\nJ 1  BK  W",
                tables=[
                    Table(
                        headers=["Pin", "Wire"],
                        rows=[TableRow(cells=["J36", "motor stator"], page=26)],
                        page=26,
                    )
                ],
            ),
            ExtractedPage(
                number=27,
                text="WIRING DIAGRAM\nh o l d   C y c l e   S t a r t   P a u s e",
            ),
        ],
    )
    chunks = chunk_document(document)
    assert all(c.page != 27 for c in chunks)
    assert any(c.kind == "table_row" and "J36" in c.text for c in chunks)
    assert not any("h o ld" in (c.text or "") or "h o l d" in (c.text or "") for c in chunks)


def test_naive_fixed_chunker_can_split_code_from_remedy():
    """Control: a 40-char window severs F6E1 from its remedy on purpose."""
    long = (
        "F5E4 Door not open error. Make sure to open and close. "
        "F6E1 No communication from the HMI detected by ACU. "
        "See Test #2: Human-Machine Interface (HMI), page 14."
    )
    document = ExtractedDocument(
        path="synthetic",
        extractor="pypdf",
        pages=[ExtractedPage(number=8, text=long)],
    )
    chunks = chunk_document(document, strategy="naive_fixed")
    # With size 200 default the whole thing may fit; force via metadata path —
    # re-call internal by setting short text pattern: use chunker with size by
    # temporarily relying on default and asserting at least one chunk exists.
    assert chunks
    # Explicit small window: patch by calling with strategy and checking split
    from repair_assistant.parsing import chunker as chunker_mod

    small = chunker_mod._naive_fixed_chunks(document, None, None, None, size=40)
    codes_only = [c for c in small if "F6E1" in c.error_codes and "Test #2" not in c.text]
    remedy_only = [c for c in small if "Test #2" in c.text and "F6E1" not in c.error_codes]
    assert codes_only or remedy_only, "fixed-size windows should orphan code or remedy"
