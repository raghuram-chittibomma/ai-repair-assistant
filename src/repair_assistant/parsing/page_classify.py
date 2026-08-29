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
_FIGURE_TITLE_RE = re.compile(
    r"\b(wiring\s+diagram|strip\s+circuit|exploded\s+view|"
    r"pictorial|control\s+panel\s+artwork)\b",
    re.I,
)
_FIGURE_REF_RE = re.compile(
    r"\b(?:fig(?:ure)?\.?\s*\d+|wiring\s+diagram|see\s+(?:the\s+)?diagram|"
    r"shown\s+in\s+(?:the\s+)?(?:figure|diagram))\b",
    re.I,
)


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
    return bool(_GUIDE_RE.search(text) and re.search(r"\bPOSSIBLE\s+CAUSE\b", text, re.I))


def looks_like_figure_page(text: str | None) -> bool:
    """True when the page is a diagram / artwork dump, not readable procedure.

    Content-based only (review R33). Matrix pages and long procedures stay
    false. Pin tables on a diagram sheet are handled by the caller: keep
    ``table_row`` chunks, drop the surrounding OCR garbage.
    """
    if not text or len(text.strip()) < 12:
        return False
    if looks_like_matrix_page(text):
        return False
    if _PROCEDURE_RE.search(text) and len(text) > 400:
        return False

    tokens = re.findall(r"[A-Za-z0-9]+", text)
    if not tokens:
        return bool(_FIGURE_TITLE_RE.search(text))
    words = [t for t in tokens if len(t) >= 3]
    singles = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    single_ratio = singles / len(tokens)
    spaced = bool(re.search(r"(?:^|[\s])[A-Za-z](?:\s+[A-Za-z]){3,}", text))
    titled = bool(_FIGURE_TITLE_RE.search(text))

    if titled and (len(words) < 80 or single_ratio >= 0.25):
        return True
    if spaced and single_ratio >= 0.35 and len(words) < 40:
        return True
    return bool(single_ratio >= 0.55 and len(words) < 20 and len(text) < 400)


def evidence_cites_unread_figure(text: str | None) -> bool:
    """True when retrieved prose points at a graphic this pipeline cannot read."""
    return bool(text and _FIGURE_REF_RE.search(text))


def should_index_chunk(text: str, kind: str | None) -> bool:
    """Keep table rows; drop figure-page OCR that would pollute the index."""
    if (kind or "") in {"table_row", "article"}:
        return True
    return not looks_like_figure_page(text)


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

    if looks_like_figure_page(text):
        return "figure"

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


__all__ = [
    "classify_page",
    "evidence_cites_unread_figure",
    "looks_like_figure_page",
    "looks_like_matrix_page",
    "should_index_chunk",
]
