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
_TOC_LEADER_RE = re.compile(r"\.{4,}\s*\d+(?:-\d+)?")
_SCHEMATIC_TITLE_RE = re.compile(
    r"\b(wiring\s+diagram|acu\s+connectors|pinouts?|strip\s+circuit)\b",
    re.I,
)
_PHOTO_ACCESS_RE = re.compile(
    r"COMPONENT ACCESS|Removing the .+\(on some models\)",
    re.I,
)
_CID_RE = re.compile(r"\(cid:\d+\)", re.I)
_SHOCK_BOX_RE = re.compile(
    r"Electrical Shock Hazard|Disconnect power before servicing",
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


def looks_like_toc_page(text: str | None) -> bool:
    """True for contents / section-intro lists, not procedure bodies."""
    if not text or len(text.strip()) < 40:
        return False
    if looks_like_matrix_page(text):
        return False
    if len(_TOC_LEADER_RE.findall(text)) >= 4:
        return True
    if re.search(r"TABLE OF CONTENTS", text, re.I):
        return True
    test_hits = len(re.findall(r"TEST\s*#\s*\d+", text, re.I))
    if test_hits >= 8 and re.search(r"Section\s+\d+\s*:", text, re.I):
        if not re.search(r"^\s*1\.\s", text, re.M):
            return True
    return False


def looks_like_schematic_page(text: str | None) -> bool:
    """True for wiring / pinout sheets that should not be indexed as prose."""
    if not text or len(text.strip()) < 12:
        return False
    if looks_like_matrix_page(text) or looks_like_toc_page(text):
        return False
    # Procedure pages often include a strip circuit under the steps.
    if _PROCEDURE_RE.search(text) and len(text) > 800:
        return False
    return bool(_SCHEMATIC_TITLE_RE.search(text) and not _PROCEDURE_RE.search(text))


def looks_like_photo_access_page(text: str | None) -> bool:
    """True for component-access pages that mix photos with numbered steps."""
    if not text or looks_like_toc_page(text) or looks_like_schematic_page(text):
        return False
    if looks_like_matrix_page(text):
        return False
    return bool(_PHOTO_ACCESS_RE.search(text) and re.search(r"Figure\s+\d+", text, re.I))


def looks_like_figure_page(text: str | None) -> bool:
    """True when the page is a diagram / artwork dump, not readable procedure.

    Content-based only (review R33). Matrix pages and long procedures stay
    false. Pin tables on a diagram sheet are handled by the caller: keep
    ``table_row`` chunks, drop the surrounding OCR garbage.
    """
    if not text or len(text.strip()) < 12:
        return False
    if looks_like_matrix_page(text) or looks_like_toc_page(text):
        return False
    if _PROCEDURE_RE.search(text) and len(text) > 400:
        return False
    if looks_like_schematic_page(text):
        return True

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


def looks_like_junk_table(table: Table) -> bool:
    """True for artwork / warning-box / CID grids that are not data tables."""
    headers = [str(h).strip() for h in (table.headers or []) if h and str(h).strip()]
    cells: list[str] = []
    for row in table.rows:
        for cell in row.cells:
            if cell and str(cell).strip():
                cells.append(str(cell).strip())
    nonempty = headers + cells
    if not nonempty:
        return True
    total_slots = len(table.headers or []) + sum(len(r.cells) for r in table.rows)
    if total_slots >= 8 and len(nonempty) / max(total_slots, 1) < 0.15:
        return True
    cid_n = sum(1 for c in nonempty if _CID_RE.search(c))
    if cid_n and cid_n >= max(1, len(nonempty) * 0.5):
        return True
    if all(_SHOCK_BOX_RE.search(c) for c in nonempty):
        return True
    return bool(len(nonempty) <= 4 and all(len(c) <= 8 for c in nonempty))


def evidence_cites_unread_figure(text: str | None) -> bool:
    """True when retrieved prose points at a graphic this pipeline cannot read."""
    return bool(text and _FIGURE_REF_RE.search(text))


def should_index_chunk(text: str, kind: str | None) -> bool:
    """Keep table rows; drop figure-page OCR that would pollute the index."""
    if (kind or "") in {"table_row", "article"}:
        return True
    return not (looks_like_schematic_page(text) or looks_like_figure_page(text))


def classify_layout(*, text: str, tables: list[Table], partition: bool = False) -> str:
    """Return layout kind from page text + tables (no page-number routing)."""
    if looks_like_matrix_page(text):
        return "matrix"
    if looks_like_toc_page(text):
        return "toc"
    if looks_like_schematic_page(text):
        return "schematic"
    if looks_like_figure_page(text):
        return "figure"
    if looks_like_photo_access_page(text):
        return "photo_access"
    if tables:
        total_cells = sum(len(t.rows) * max(len(t.headers), 1) for t in tables)
        if total_cells >= 12 or len(tables) >= 2:
            return "table_heavy"
    if partition:
        return "multi_column"
    if _PROCEDURE_RE.search(text):
        return "multi_column"
    return "default"


def classify_page(
    page: Any,
    *,
    page_no: int,
    tables: list[Table],
    words: list[dict] | None = None,
) -> str:
    """Return layout kind for hybrid routing.

    Classification is content/geometry based — never keyed to absolute page
    numbers or a specific corpus document.
    """
    _ = page_no  # call-site compatibility; not used for routing
    words = words if words is not None else (page.extract_words() or [])
    text = page.extract_text() or ""
    partition = detect_partition_x(page, words) is not None
    return classify_layout(text=text, tables=tables, partition=partition)


__all__ = [
    "classify_layout",
    "classify_page",
    "evidence_cites_unread_figure",
    "looks_like_figure_page",
    "looks_like_junk_table",
    "looks_like_matrix_page",
    "looks_like_photo_access_page",
    "looks_like_schematic_page",
    "looks_like_toc_page",
    "should_index_chunk",
]
