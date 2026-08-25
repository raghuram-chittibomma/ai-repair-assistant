"""Extractor candidates behind one interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from .language import detect_language
from .models import BBox, Block, ExtractedDocument, ExtractedPage, Table, TableRow
from .pua import map_pua


class Extractor(Protocol):
    name: str

    def extract(self, path: Path | str) -> ExtractedDocument: ...


def _producer(path: Path) -> str | None:
    try:
        reader = PdfReader(str(path))
        if reader.metadata and reader.metadata.producer:
            return str(reader.metadata.producer).strip() or None
    except Exception:
        return None
    return None


class PypdfExtractor:
    """Baseline: page text only, no tables. Expected to lose structure."""

    name = "pypdf"

    def extract(self, path: Path | str) -> ExtractedDocument:
        path = Path(path)
        reader = PdfReader(str(path))
        pages: list[ExtractedPage] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(
                ExtractedPage(
                    number=index,
                    text=text,
                    blocks=[Block(text=text, page=index, kind="text")],
                    tables=[],
                    language=detect_language(text),
                )
            )
        return ExtractedDocument(
            path=str(path),
            extractor=self.name,
            pages=pages,
            producer=_producer(path),
        )


class PdfplumberExtractor:
    """Table-aware extraction via pdfplumber."""

    name = "pdfplumber"

    def extract(self, path: Path | str) -> ExtractedDocument:
        import pdfplumber

        path = Path(path)
        pages: list[ExtractedPage] = []
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                tables = [_convert_table(t, index) for t in (page.extract_tables() or []) if t]
                tables = [t for t in tables if t is not None]
                pages.append(
                    ExtractedPage(
                        number=index,
                        text=text,
                        blocks=[Block(text=map_pua(text), page=index, kind="text")],
                        tables=tables,
                        language=detect_language(text),
                    )
                )
        return ExtractedDocument(
            path=str(path),
            extractor=self.name,
            pages=pages,
            producer=_producer(path),
        )


class PymupdfExtractor:
    """Layout + table extraction via PyMuPDF."""

    name = "pymupdf"

    def extract(self, path: Path | str) -> ExtractedDocument:
        import pymupdf

        path = Path(path)
        doc = pymupdf.open(str(path))
        pages: list[ExtractedPage] = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            blocks: list[Block] = []
            for block in page.get_text("blocks"):
                # block: x0, y0, x1, y1, text, block_no, block_type
                if len(block) < 5 or block[6] != 0:
                    continue
                btext = map_pua(block[4] or "")
                if not btext.strip():
                    continue
                blocks.append(
                    Block(
                        text=btext,
                        page=index,
                        kind="text",
                        bbox=BBox(block[0], block[1], block[2], block[3]),
                    )
                )
            tables: list[Table] = []
            try:
                finder = page.find_tables()
                for table in finder.tables:
                    converted = _convert_matrix(table.extract(), index)
                    if converted:
                        tables.append(converted)
            except Exception:
                pass
            pages.append(
                ExtractedPage(
                    number=index,
                    text=text,
                    blocks=blocks or [Block(text=map_pua(text), page=index, kind="text")],
                    tables=tables,
                    language=detect_language(text),
                )
            )
        doc.close()
        return ExtractedDocument(
            path=str(path),
            extractor=self.name,
            pages=pages,
            producer=_producer(path),
        )


def _convert_table(raw: list[list[str | None]], page: int) -> Table | None:
    if not raw or len(raw) < 2:
        return None
    headers = [map_pua((c or "").strip()) for c in raw[0]]
    rows: list[TableRow] = []
    for row in raw[1:]:
        cells = [map_pua((c or "").strip()) for c in row]
        if any(cells):
            rows.append(TableRow(cells=cells, page=page))
    if not rows:
        return None
    return Table(headers=headers, rows=rows, page=page)


def _convert_matrix(raw: list[list[str | None]] | None, page: int) -> Table | None:
    if not raw:
        return None
    return _convert_table(raw, page)


def available_extractors() -> list[Extractor]:
    """Return extractors whose dependencies import cleanly."""
    extractors: list[Extractor] = [PypdfExtractor()]
    try:
        import pdfplumber  # noqa: F401

        extractors.append(PdfplumberExtractor())
    except ImportError:
        pass
    try:
        import pymupdf  # noqa: F401

        extractors.append(PymupdfExtractor())
    except ImportError:
        pass
    return extractors


def get_extractor(name: str) -> Extractor:
    for extractor in available_extractors():
        if extractor.name == name:
            return extractor
    raise KeyError(f"unknown or unavailable extractor: {name}")
