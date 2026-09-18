"""Attach native PDF page-ranges or page rasters for semantic evidence (ADR-0050/0051)."""

from __future__ import annotations

import contextlib
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from repair_assistant.corpus.identity import inspect
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.qa.context import Citation
from repair_assistant.qa.env import semantic_evidence_max_pages
from repair_assistant.qa.page_images import (
    PageImage,
    document_pdf_path,
    ensure_page_raster,
)
from repair_assistant.retrieval.search import Hit
from repair_assistant.semantic.pdf_extract import write_pdf_part

_log = logging.getLogger("repair_assistant.qa")

SEMANTIC_LAYOUT_NOTE = (
    "Note: for evidence blocks tagged modality: semantic_pdf, the attached PDF "
    "page-range file and/or page images labeled [n] ARE the evidence body; the "
    "fenced stub is a locator only. Cite [n] from what is visible in that "
    "attachment. Do not invent content that is not in the attachment (or in a "
    "semantic_text_fallback / structured_text block)."
)


@dataclass
class SemanticEvidenceAttach:
    """PDF file parts and/or rasters for semantic units in the evidence pack."""

    pdf_paths: list[Path] = field(default_factory=list)
    #: Cite index → native PDF page-range path (text PDFs only).
    pdf_by_index: dict[int, Path] = field(default_factory=dict)
    page_images: list[PageImage] = field(default_factory=list)
    #: Cite indexes that successfully got a PDF part and/or at least one raster.
    attached_indexes: set[int] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    temp_dir: Path | None = None

    def cleanup(self) -> None:
        for path in self.pdf_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _log.warning("Could not delete evidence PDF %s", path)
        if self.temp_dir is not None:
            with contextlib.suppress(OSError):
                self.temp_dir.rmdir()


def _unit_page_span(hit: Hit) -> tuple[int, int] | None:
    meta = hit.metadata if isinstance(hit.metadata, dict) else {}
    start = meta.get("page_start")
    end = meta.get("page_end")
    try:
        if start is not None:
            start_i = int(start)
            end_i = int(end) if end is not None else start_i
            if start_i >= 1 and end_i >= start_i:
                return start_i, end_i
    except (TypeError, ValueError):
        pass
    if hit.page is not None and int(hit.page) >= 1:
        page = int(hit.page)
        return page, page
    return None


def attach_semantic_pdf_evidence(
    hits: list[Hit],
    citations: list[Citation],
    manifest: Manifest | None,
) -> SemanticEvidenceAttach:
    """Build native PDF parts (text PDFs) or page rasters (scanned) for units."""
    out = SemanticEvidenceAttach()
    if manifest is None or not hits or not citations:
        return out

    cite_by_chunk = {c.chunk_id: c for c in citations}
    seen: set[tuple[str, int, int]] = set()
    pages_used = 0
    max_pages = semantic_evidence_max_pages()
    temp_dir: Path | None = None

    for hit in hits:
        if not getattr(hit, "is_semantic_unit", False):
            continue
        cite = cite_by_chunk.get(hit.chunk_id)
        if cite is None:
            continue
        span = _unit_page_span(hit)
        if span is None:
            continue
        start, end = span
        key = (hit.doc_id, start, end)
        if key in seen:
            continue
        seen.add(key)

        pdf = document_pdf_path(manifest, hit.doc_id)
        if pdf is None:
            continue
        try:
            facts = inspect(pdf)
        except Exception:  # noqa: BLE001 — best-effort modality
            facts = None
        scanned = bool(facts and facts.looks_scanned)

        if scanned:
            attached_any = False
            for page in range(start, end + 1):
                if pages_used >= max_pages:
                    out.notes.append(
                        f"Semantic page rasters capped at {max_pages} "
                        f"(skipped remaining pages for [{cite.index}])."
                    )
                    break
                cache = ensure_page_raster(manifest, hit.doc_id, page)
                if cache is None or not cache.is_file():
                    continue
                out.page_images.append(
                    PageImage(
                        index=cite.index,
                        doc_id=hit.doc_id,
                        page=page,
                        jpeg_bytes=cache.read_bytes(),
                    )
                )
                pages_used += 1
                attached_any = True
            if attached_any:
                out.attached_indexes.add(cite.index)
            continue

        if temp_dir is None:
            temp_dir = Path(tempfile.mkdtemp(prefix="repair-evidence-pdf-"))
            out.temp_dir = temp_dir
        dest = temp_dir / f"cite{cite.index}-{hit.doc_id}-p{start}-{end}.pdf"
        try:
            write_pdf_part(pdf, start_page=start, end_page=end, dest=dest)
        except Exception:  # noqa: BLE001
            _log.warning(
                "Failed to slice PDF for %s pp.%s-%s", hit.doc_id, start, end,
                exc_info=True,
            )
            continue
        out.pdf_paths.append(dest)
        out.pdf_by_index[cite.index] = dest
        out.attached_indexes.add(cite.index)

    if out.pdf_paths or out.page_images:
        out.notes.insert(0, SEMANTIC_LAYOUT_NOTE)
    return out


__all__ = [
    "SEMANTIC_LAYOUT_NOTE",
    "SemanticEvidenceAttach",
    "attach_semantic_pdf_evidence",
]
