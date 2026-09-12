"""Gated PDF page rasters for late-fusion vision (ADR-0035)."""

from __future__ import annotations

import logging
import re
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
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def page_image_url(doc_id: str, page: int) -> str:
    return f"/v1/documents/{doc_id}/pages/{int(page)}/image"


def safe_doc_id(doc_id: str) -> str | None:
    text = (doc_id or "").strip()
    if not text or ".." in text or not _DOC_ID_RE.fullmatch(text):
        return None
    return text


def citation_public_dict(cite) -> dict:
    """API / SSE citation: page URL plus optional table-row or prose overlay."""
    doc_id = str(getattr(cite, "doc_id", "") or "")
    page = getattr(cite, "page", None)
    payload = {
        "index": int(getattr(cite, "index", 0) or 0),
        "doc_id": doc_id,
        "chunk_id": str(getattr(cite, "chunk_id", "") or ""),
        "label": str(getattr(cite, "label", "") or ""),
        "page": page,
    }
    clean = safe_doc_id(doc_id)
    if clean and page is not None and int(page) >= 1:
        payload["url"] = page_image_url(clean, int(page))
    bbox = getattr(cite, "bbox", None)
    width = getattr(cite, "page_width", None)
    height = getattr(cite, "page_height", None)
    if isinstance(bbox, dict) and width and height:
        payload["bbox"] = bbox
        payload["page_width"] = float(width)
        payload["page_height"] = float(height)
    return payload


def figure_page_payloads(rows: list) -> list[dict]:
    """JSON for ask/diagnose: citation index, page, and UI image URL."""
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for row in rows or []:
        if isinstance(row, dict):
            doc_id = str(row.get("doc_id") or "")
            page = row.get("page")
            index = int(row.get("index") or 0)
        else:
            doc_id = str(getattr(row, "doc_id", "") or "")
            page = getattr(row, "page", None)
            index = int(getattr(row, "index", 0) or 0)
        if page is None or int(page) < 1 or not safe_doc_id(doc_id):
            continue
        key = (doc_id, int(page))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "index": index,
                "doc_id": doc_id,
                "page": int(page),
                "url": page_image_url(doc_id, int(page)),
            }
        )
    return out


def ensure_page_raster(manifest: Manifest, doc_id: str, page: int) -> Path | None:
    """Return the cached JPEG path, rendering from the local PDF if needed."""
    clean = safe_doc_id(doc_id)
    if clean is None or int(page) < 1:
        return None
    cache = raster_cache_path(manifest, clean, int(page))
    if cache.is_file() and cache.stat().st_size > 0:
        return cache
    pdf = document_pdf_path(manifest, clean)
    if pdf is None:
        return None
    jpeg = raster_pdf_page(pdf, int(page), cache)
    if not jpeg:
        return None
    return cache if cache.is_file() else None


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
