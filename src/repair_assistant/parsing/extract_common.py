"""Shared PDF extract helpers (avoid circular imports between extractors and hybrid)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .models import Table, TableRow
from .pua import map_pua


def pdf_producer(path: Path) -> str | None:
    try:
        reader = PdfReader(str(path))
        if reader.metadata and reader.metadata.producer:
            return str(reader.metadata.producer).strip() or None
    except Exception:
        return None
    return None


def convert_table(raw: list[list[str | None]], page: int) -> Table | None:
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


__all__ = ["convert_table", "pdf_producer"]
