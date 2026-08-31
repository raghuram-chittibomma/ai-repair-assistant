"""Hybrid page-scoped PDF extraction (ADR-0024)."""

from __future__ import annotations

from pathlib import Path

from .canonical import CanonicalDocument, build_canonical
from .column_order import reorder_page_text
from .extract_common import convert_table, pdf_producer
from .language import detect_language
from .models import Block, ExtractedDocument, ExtractedPage, Table
from .page_classify import classify_page, looks_like_junk_table
from .parse_quality import PageAudit, audit_page, quality_override_for


def _extract_tables(page: object, page_no: int) -> list[Table]:
    tables = [convert_table(t, page_no) for t in (page.extract_tables() or []) if t]
    return [t for t in tables if t is not None]


def _layout_prose_text(path: Path, page_index: int) -> str | None:
    """PyMuPDF4LLM single-page text when the optional dependency is installed."""
    try:
        import pymupdf4llm
    except ImportError:
        return None
    try:
        return pymupdf4llm.to_text(str(path), pages=[page_index]) or None
    except Exception:
        return None


def _prose_for_page(
    path: Path,
    page: object,
    page_no: int,
    layout_kind: str,
    *,
    force_layout: bool = False,
) -> tuple[str, str]:
    """Return (text, source_tag).

    ``matrix`` pages keep pdfplumber LTR text — vertical rules are table columns.
    ``multi_column`` / ``photo_access`` use left-then-right reorder (or layout ML).
    """
    if layout_kind in {"matrix", "figure", "schematic", "toc"}:
        return page.extract_text() or "", "pdfplumber"

    if force_layout:
        layout_text = _layout_prose_text(path, page_no - 1)
        if layout_text and layout_text.strip():
            return layout_text, "pymupdf4llm"

    if layout_kind in {"multi_column", "photo_access"}:
        reordered, did_reorder, _ = reorder_page_text(page)
        if did_reorder and reordered.strip():
            return reordered, "column_reorder"

    if force_layout:
        reordered, did_reorder, _ = reorder_page_text(page)
        if did_reorder and reordered.strip():
            return reordered, "column_reorder"

    return page.extract_text() or "", "pdfplumber"


def _audit_kwargs(path: Path, page_no: int) -> dict:
    override = quality_override_for(path, page_no)
    if not override:
        return {}
    return {
        "phrase_markers": list(override.phrase_markers) or None,
        "expect_steps": list(override.expect_steps) or None,
    }


class HybridExtractor:
    """Route table vs prose extraction per page; audit and retry layout."""

    name = "hybrid"

    def extract(self, path: Path | str) -> ExtractedDocument:
        import pdfplumber

        path = Path(path)
        pages: list[ExtractedPage] = []
        audits: list[PageAudit] = []

        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                tables = [
                    t for t in _extract_tables(page, index) if not looks_like_junk_table(t)
                ]
                layout_kind = classify_page(page, page_no=index, tables=tables)
                override_kwargs = _audit_kwargs(path, index)

                text, source = _prose_for_page(
                    path, page, index, layout_kind, force_layout=False
                )

                audit = audit_page(
                    page=index,
                    text=text,
                    tables=tables,
                    layout_kind=layout_kind,
                    prose_source=source,
                    **override_kwargs,
                )

                if audit.suspect() and layout_kind in {"multi_column", "photo_access"}:
                    retry_text, retry_source = _prose_for_page(
                        path, page, index, layout_kind, force_layout=True
                    )
                    if retry_source != source or retry_text != text:
                        text, source = retry_text, retry_source
                        audit = audit_page(
                            page=index,
                            text=text,
                            tables=tables,
                            layout_kind=layout_kind,
                            prose_source=source,
                            **override_kwargs,
                        )
                        audit.retried = True

                audits.append(audit)
                pages.append(
                    ExtractedPage(
                        number=index,
                        text=text,
                        blocks=[Block(text=text, page=index, kind="text")],
                        tables=tables,
                        language=detect_language(text),
                    )
                )

        doc = ExtractedDocument(
            path=str(path),
            extractor=self.name,
            pages=pages,
            producer=pdf_producer(path),
        )
        canonical = build_canonical(doc, page_audits=audits)
        doc.parse_audit = canonical.to_json()
        return doc


class Pymupdf4llmExtractor:
    """Layout-aware full-document extraction via pymupdf4llm (optional dep)."""

    name = "pymupdf4llm"

    def extract(self, path: Path | str) -> ExtractedDocument:
        path = Path(path)
        try:
            import pymupdf4llm
        except ImportError as exc:
            raise ImportError(
                "pymupdf4llm is not installed; pip install -e '.[layout]'"
            ) from exc

        pymupdf4llm.to_text(str(path)) or ""
        # Tables still from pdfplumber for binding fidelity.
        import pdfplumber

        pages: list[ExtractedPage] = []
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                page_text = pymupdf4llm.to_text(str(path), pages=[index - 1]) or ""
                tables = _extract_tables(page, index)
                pages.append(
                    ExtractedPage(
                        number=index,
                        text=page_text,
                        blocks=[Block(text=page_text, page=index, kind="text")],
                        tables=tables,
                        language=detect_language(page_text),
                    )
                )

        return ExtractedDocument(
            path=str(path),
            extractor=self.name,
            pages=pages,
            producer=pdf_producer(path),
        )


def extract_with_audit(path: Path | str) -> tuple[ExtractedDocument, CanonicalDocument]:
    """Hybrid extract returning document + canonical tree."""
    extractor = HybridExtractor()
    document = extractor.extract(path)
    canonical = build_canonical(
        document,
        page_audits=[
            PageAudit(
                page=a["page"],
                layout_kind=a["layout_kind"],
                prose_source=a["prose_source"],
                flags=list(a.get("flags") or []),
                retried=bool(a.get("retried")),
            )
            for a in (document.parse_audit or {}).get("page_audits", [])
        ],
    )
    return document, canonical


__all__ = [
    "HybridExtractor",
    "Pymupdf4llmExtractor",
    "extract_with_audit",
]
