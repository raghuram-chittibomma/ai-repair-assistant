"""Page layout classification for hybrid extraction (ADR-0024)."""

from __future__ import annotations

import re
from typing import Any

from .column_order import detect_partition_x
from .models import Table

_GUIDE_RE = re.compile(r"TROUBLESHOOTING\s+GUIDE\s*#\s*\d+", re.I)
_MATRIX_COLS_RE = re.compile(
    r"PROBLEM.{0,40}POSSIBLE\s+CAUSE|POSSIBLE\s+CAUSE.{0,40}CHECKS",
    re.I | re.S,
)
_PROCEDURE_RE = re.compile(r"TEST\s+PROCEDURES|TEST\s*#\s*\d+", re.I)


def looks_like_matrix_page(text: str | None) -> bool:
    """True when page is a troubleshooting matrix (not newspaper columns).

    Vertical rules on these pages are *table* column separators. Applying
    left-then-right reading order severs Problem/Cause from Checks & tests.
    Prefer pdfplumber LTR ``extract_text`` + matrix prose fallback instead.
    """
    if not text or len(text) < 80:
        return False
    if _GUIDE_RE.search(text) and _MATRIX_COLS_RE.search(text):
        return True
    if _GUIDE_RE.search(text) and re.search(r"\bPOSSIBLE\s+CAUSE\b", text, re.I):
        return True
    return False


def classify_page(
    page: Any,
    *,
    page_no: int,
    tables: list[Table],
    words: list[dict] | None = None,
) -> str:
    """Return layout kind: ``matrix``, ``table_heavy``, ``multi_column``, or ``default``.

    Classification is content/geometry based — never keyed to absolute page
    numbers or a specific corpus document.
    """
    _ = page_no  # call-site compatibility; not used for routing
    words = words if words is not None else (page.extract_words() or [])
    text = page.extract_text() or ""

    # Matrix pages first — before multi_column — so table partitions are not
    # treated as newspaper reading-order breaks.
    if looks_like_matrix_page(text):
        return "matrix"

    if tables:
        total_cells = sum(len(t.rows) * max(len(t.headers), 1) for t in tables)
        if total_cells >= 12 or len(tables) >= 2:
            return "table_heavy"

    if detect_partition_x(page, words) is not None:
        return "multi_column"

    # Procedure pages without a clear vertical partition still need column care.
    if _PROCEDURE_RE.search(text):
        return "multi_column"

    return "default"


__all__ = ["classify_page", "looks_like_matrix_page"]
