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
                text="ignored",
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
    chunks = chunk_document(document, strategy="structured", doc_id="tech-sheet-w11320651")
    table_chunks = [c for c in chunks if c.kind == "table_row"]
    assert table_chunks
    assert table_chunks[0].error_codes == ["F6E1"]
    assert "No communication from the HMI" in table_chunks[0].text
    assert "Test #2" in table_chunks[0].text


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
