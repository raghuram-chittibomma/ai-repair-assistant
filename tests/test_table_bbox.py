"""Table-row bbox matching (ADR-0037) — no live PDF."""

from __future__ import annotations

from repair_assistant.parsing.models import BBox, Table, TableRow
from repair_assistant.parsing.table_bbox import (
    attach_row_bboxes,
    layout_metadata,
    normalize_row_cells,
)


class _FoundRow:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        self.bbox = bbox


class _FoundTable:
    def __init__(self, extracted: list[list[str]], boxes: list[tuple]) -> None:
        self._extracted = extracted
        self.rows = [_FoundRow(b) for b in boxes]

    def extract(self) -> list[list[str]]:
        return self._extracted


class _Finder:
    def __init__(self, tables: list[_FoundTable]) -> None:
        self.tables = tables


class _Page:
    width = 612.0
    height = 792.0

    def __init__(self, tables: list[_FoundTable]) -> None:
        self._tables = tables

    def find_tables(self) -> _Finder:
        return _Finder(self._tables)


def test_find_tables_list_return_matches_rows() -> None:
    """Current pdfplumber returns a list from find_tables(), not TableFinder."""
    text_table = Table(
        headers=["Error Code", "Description"],
        rows=[TableRow(cells=["F5E2", "Door lock"], page=8)],
        page=8,
    )
    found = _FoundTable(
        [["Error Code", "Description"], ["F5E2", "Door lock"]],
        [(40, 40, 500, 60), (40, 80, 500, 100)],
    )

    class _ListPage:
        width = 612.0
        height = 792.0

        def find_tables(self):
            return [found]

    attach_row_bboxes([text_table], _ListPage())
    assert text_table.rows[0].bbox == BBox(40, 80, 500, 100)


def test_unique_row_text_gets_bbox() -> None:
    text_table = Table(
        headers=["Error Code", "Description"],
        rows=[
            TableRow(cells=["F5E2", "Door lock"], page=8),
            TableRow(cells=["F6E1", "Drive motor"], page=8),
        ],
        page=8,
    )
    found = _FoundTable(
        [["Error Code", "Description"], ["F5E2", "Door lock"], ["F6E1", "Drive motor"]],
        [(40, 40, 500, 60), (40, 80, 500, 100), (40, 120, 500, 140)],
    )
    attach_row_bboxes([text_table], _Page([found]))
    assert text_table.page_width == 612.0
    assert text_table.rows[0].bbox == BBox(40, 80, 500, 100)
    assert text_table.rows[1].bbox == BBox(40, 120, 500, 140)
    meta = layout_metadata(text_table.rows[0], text_table)
    assert meta["bbox"]["y0"] == 80
    assert meta["bbox_space"] == "pdfplumber_pt"


def test_duplicate_row_text_gets_no_bbox() -> None:
    text_table = Table(
        headers=["A", "B"],
        rows=[
            TableRow(cells=["same", "row"], page=1),
            TableRow(cells=["same", "row"], page=1),
        ],
        page=1,
    )
    found = _FoundTable(
        [["A", "B"], ["same", "row"], ["same", "row"]],
        [(0, 0, 10, 10), (0, 20, 10, 30), (0, 40, 10, 50)],
    )
    attach_row_bboxes([text_table], _Page([found]))
    assert text_table.rows[0].bbox is None
    assert text_table.rows[1].bbox is None


def test_no_find_tables_leaves_bbox_empty() -> None:
    table = Table(
        headers=["A"],
        rows=[TableRow(cells=["x"], page=1)],
        page=1,
    )

    class _Empty:
        width = 100
        height = 100

        def find_tables(self):
            raise RuntimeError("no tables")

    attach_row_bboxes([table], _Empty())
    assert table.rows[0].bbox is None
    assert table.page_width == 100


def test_normalize_row_cells_strips() -> None:
    assert normalize_row_cells(["  F5E2 ", None]) == ("F5E2", "")
