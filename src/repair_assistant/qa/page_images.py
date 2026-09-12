"""Gated PDF page rasters for late-fusion vision (ADR-0035)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from repair_assistant.corpus.manifest import Manifest
from repair_assistant.parsing.page_classify import (
    evidence_cites_unread_figure,
    looks_like_figure_page,
    looks_like_photo_access_page,
    looks_like_schematic_page,
)
from repair_assistant.qa.context import Citation
from repair_assistant.retrieval.search import Hit

_log = logging.getLogger("repair_assistant.qa")

MAX_PAGE_IMAGES = 3
RASTER_DPI = 150


@dataclass(frozen=True)
class PageImageSpec:
    index: int
    doc_id: str
    page: int


@dataclass(frozen=True)
class PageImage:
    index: int
    doc_id: str
    page: int
    jpeg_bytes: bytes


def hit_needs_page_image(text: str | None) -> bool:
    """True when this hit should try to attach a page raster."""
    return bool(
        looks_like_figure_page(text)
        or looks_like_schematic_page(text)
        or looks_like_photo_access_page(text)
        or evidence_cites_unread_figure(text)
    )


def document_pdf_path(manifest: Manifest, doc_id: str) -> Path | None:
    doc = manifest.by_doc_id.get(doc_id)
    if doc is None:
        return None
    path = manifest.documents_dir / doc.local_filename
    return path if path.is_file() else None


def raster_cache_path(manifest: Manifest, doc_id: str, page: int) -> Path:
    return (
        manifest.root
        / "corpus"
        / "parsed"
        / doc_id
        / "page-rasters"
        / f"p{page:04d}.jpg"
    )


def plan_page_images(
    hits: list[Hit],
    citations: list[Citation],
    manifest: Manifest | None,
    *,
    limit: int = MAX_PAGE_IMAGES,
) -> list[PageImageSpec]:
    """Pick unique gated (doc_id, page) pairs that have a local PDF."""
    if manifest is None or limit <= 0:
        return []
    out: list[PageImageSpec] = []
    seen: set[tuple[str, int]] = set()
    for cite, hit in zip(citations, hits, strict=False):
        page = cite.page if cite.page is not None else hit.page
        if page is None or int(page) < 1:
            continue
        if not hit_needs_page_image(hit.text or cite.block_text):
            continue
        key = (hit.doc_id, int(page))
        if key in seen:
            continue
        if document_pdf_path(manifest, hit.doc_id) is None:
            continue
        seen.add(key)
        out.append(PageImageSpec(index=cite.index, doc_id=hit.doc_id, page=int(page)))
        if len(out) >= limit:
            break
    return out


def raster_pdf_page(pdf_path: Path, page: int, cache_path: Path) -> bytes | None:
    """Render a 1-based PDF page to JPEG, using cache_path when present."""
    if cache_path.is_file() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()
    try:
        import pymupdf
    except ImportError:
        _log.warning("pymupdf is not installed; skip page raster")
        return None
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception:
        _log.warning("Could not open PDF for raster: %s", pdf_path)
        return None
    try:
        if page < 1 or page > doc.page_count:
            return None
        pix = doc[page - 1].get_pixmap(dpi=RASTER_DPI)
        jpeg = pix.tobytes("jpeg")
    except Exception:
        _log.warning("Could not raster PDF page %s of %s", page, pdf_path)
        return None
    finally:
        doc.close()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(jpeg)
    except OSError:
        _log.warning("Could not cache page raster at %s", cache_path)
    return jpeg


def raster_page_images(
    specs: list[PageImageSpec],
    manifest: Manifest | None,
) -> list[PageImage]:
    if manifest is None:
        return []
    images: list[PageImage] = []
    for spec in specs:
        pdf = document_pdf_path(manifest, spec.doc_id)
        if pdf is None:
            continue
        jpeg = raster_pdf_page(pdf, spec.page, raster_cache_path(manifest, spec.doc_id, spec.page))
        if not jpeg:
            continue
        images.append(
            PageImage(
                index=spec.index,
                doc_id=spec.doc_id,
                page=spec.page,
                jpeg_bytes=jpeg,
            )
        )
    return images


def collect_page_images(
    hits: list[Hit],
    citations: list[Citation],
    manifest: Manifest | None,
    *,
    limit: int = MAX_PAGE_IMAGES,
) -> list[PageImage]:
    return raster_page_images(plan_page_images(hits, citations, manifest, limit=limit), manifest)


def attach_gated_images(
    hits: list[Hit],
    citations: list[Citation],
    evidence_text: str,
    manifest: Manifest | None,
    *,
    query: str = "",
    enabled: bool = True,
) -> tuple[str, list[Citation], list[PageImage]]:
    """Re-note evidence and raster gated pages when vision is enabled."""
    if not enabled or manifest is None:
        return evidence_text, citations, []
    specs = plan_page_images(hits, citations, manifest)
    images = raster_page_images(specs, manifest)
    if not images:
        return evidence_text, citations, []
    from repair_assistant.qa.context import format_evidence

    noted, cited = format_evidence(
        hits,
        query=query,
        manifest=manifest,
        attached_indexes={image.index for image in images},
    )
    return noted, cited, images
