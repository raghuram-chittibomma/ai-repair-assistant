"""Thin PDF page-text extract for semantic units (ADR-0049).

Not the hybrid parser: no tables engine, no contextual enrichment, no
section-path injection. Used only to materialise ``source_text`` for a
page-range marker after boundaries are chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfOutlinePart:
    """One logical PDF part for native-PDF segmentation windows."""

    title: str
    start_page: int
    end_page: int


def page_count(pdf_path: Path) -> int:
    import fitz  # pymupdf

    with fitz.open(str(pdf_path)) as doc:
        return int(doc.page_count)


def extract_page_range_text(
    pdf_path: Path,
    *,
    start_page: int,
    end_page: int,
) -> str:
    """Verbatim text for pages ``start_page``..``end_page`` (1-based inclusive)."""
    if start_page < 1 or end_page < start_page:
        return ""
    import fitz

    parts: list[str] = []
    with fitz.open(str(pdf_path)) as doc:
        last = min(end_page, doc.page_count)
        for page_index in range(start_page - 1, last):
            text = (doc.load_page(page_index).get_text("text") or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def outline_parts(pdf_path: Path, *, max_pages_per_part: int = 40) -> list[PdfOutlinePart]:
    """Split a PDF by outline bookmarks when present, else fixed page windows."""
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        total = int(doc.page_count)
        if total < 1:
            return []
        toc = doc.get_toc(simple=True) or []
        # Level-1 bookmarks only — chapters / major sections.
        tops = [
            (str(title).strip() or f"Part starting p.{page}", int(page))
            for level, title, page in toc
            if int(level) == 1 and int(page) >= 1
        ]
        if len(tops) >= 2:
            parts: list[PdfOutlinePart] = []
            for index, (title, start) in enumerate(tops):
                end = (tops[index + 1][1] - 1) if index + 1 < len(tops) else total
                end = max(start, min(end, total))
                # Sub-split oversized chapters.
                cursor = start
                while cursor <= end:
                    chunk_end = min(cursor + max_pages_per_part - 1, end)
                    label = title if cursor == start else f"{title} (cont. p.{cursor})"
                    parts.append(
                        PdfOutlinePart(title=label, start_page=cursor, end_page=chunk_end)
                    )
                    cursor = chunk_end + 1
            return parts

        parts = []
        cursor = 1
        while cursor <= total:
            end = min(cursor + max_pages_per_part - 1, total)
            parts.append(
                PdfOutlinePart(
                    title=f"Pages {cursor}-{end}",
                    start_page=cursor,
                    end_page=end,
                )
            )
            cursor = end + 1
        return parts


def write_pdf_part(
    pdf_path: Path,
    *,
    start_page: int,
    end_page: int,
    dest: Path,
) -> Path:
    """Write a contiguous page-range PDF for native-file upload to the model."""
    import fitz

    dest.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(pdf_path)) as src:
        out = fitz.open()
        out.insert_pdf(src, from_page=start_page - 1, to_page=end_page - 1)
        out.save(str(dest))
        out.close()
    return dest
