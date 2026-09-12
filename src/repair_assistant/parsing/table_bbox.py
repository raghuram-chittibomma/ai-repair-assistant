"""Attach pdfplumber row rectangles to extract_tables() text (ADR-0037)."""

from __future__ import annotations

from collections import defaultdict

from repair_assistant.parsing.models import BBox, Table, TableRow
from repair_assistant.parsing.pua import map_pua

BBOX_SPACE = "pdfplumber_pt"


def normalize_row_cells(cells: list | tuple | None) -> tuple[str, ...]:
    return tuple(map_pua((c or "").strip()) for c in (cells or []))


def nonempty_key(cells: list | tuple | None) -> tuple[str, ...]:
    return tuple(part for part in normalize_row_cells(cells) if part)


def bbox_from_rect(rect) -> BBox | None:
    if rect is None or len(rect) < 4:
        return None
    x0, y0, x1, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _found_tables(page: object) -> list:
    """pdfplumber find_tables() is a list; older TableFinder used .tables."""
    try:
        found = page.find_tables()
    except Exception:
        return []
    if found is None:
        return []
    tables = getattr(found, "tables", None)
    if tables is not None:
        return list(tables)
    if isinstance(found, (list, tuple)):
        return list(found)
    return []


def _found_row_entries(page: object) -> list[tuple[tuple[str, ...], tuple[str, ...], BBox]]:
    """Yield (full_key, nonempty_key, bbox) from find_tables() — not extract_tables()."""
    found_tables = _found_tables(page)
    out: list[tuple[tuple[str, ...], tuple[str, ...], BBox]] = []
    for found in found_tables:
        try:
            extracted = found.extract() or []
            rows = list(found.rows)
        except Exception:
            continue
        for cells, row in zip(extracted, rows, strict=False):
            box = bbox_from_rect(getattr(row, "bbox", None))
            if box is None:
                continue
            full = normalize_row_cells(cells)
            nonempty = nonempty_key(cells)
            if not nonempty:
                continue
            out.append((full, nonempty, box))
    return out


def _unique_map(
    entries: list[tuple[tuple[str, ...], tuple[str, ...], BBox]],
    *,
    key_index: int,
) -> dict[tuple[str, ...], BBox]:
    buckets: dict[tuple[str, ...], list[BBox]] = defaultdict(list)
    for entry in entries:
        buckets[entry[key_index]].append(entry[2])
    return {key: boxes[0] for key, boxes in buckets.items() if len(boxes) == 1}


def attach_row_bboxes(tables: list[Table], page: object) -> None:
    """Set TableRow.bbox when a find_tables() row matches uniquely by cell text."""
    width = float(getattr(page, "width", 0) or 0)
    height = float(getattr(page, "height", 0) or 0)
    for table in tables:
        if width > 0:
            table.page_width = width
        if height > 0:
            table.page_height = height

    entries = _found_row_entries(page)
    if not entries:
        return
    by_full = _unique_map(entries, key_index=0)
    by_nonempty = _unique_map(entries, key_index=1)

    for table in tables:
        for row in table.rows:
            if row.bbox is not None:
                continue
            full = normalize_row_cells(row.cells)
            box = by_full.get(full)
            if box is None:
                box = by_nonempty.get(nonempty_key(row.cells))
            row.bbox = box


def layout_metadata(row: TableRow, table: Table) -> dict:
    """Chunk metadata keys for a table row (empty when geometry is missing)."""
    out: dict = {}
    if table.page_width and table.page_height:
        out["page_width"] = float(table.page_width)
        out["page_height"] = float(table.page_height)
    if row.bbox is None:
        return out
    out["bbox"] = row.bbox.to_dict()
    out["bbox_space"] = BBOX_SPACE
    return out


__all__ = [
    "BBOX_SPACE",
    "attach_row_bboxes",
    "bbox_from_rect",
    "layout_metadata",
    "nonempty_key",
    "normalize_row_cells",
]
