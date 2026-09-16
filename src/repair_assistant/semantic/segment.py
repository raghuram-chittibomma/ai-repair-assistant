"""Ask an LLM to propose PDF page-range markers (ADR-0049).

Text PDFs: native PDF parts are uploaded to the model. Scanned PDFs: page
rasters go through the vision path. Markers are page ranges; source text is
read back with a thin PDF extract, never from the hybrid parser.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from repair_assistant.corpus.identity import inspect
from repair_assistant.prompts import prompt_digest, semantic_segment
from repair_assistant.semantic.env import (
    segment_window_pages,
    semantic_llm_model,
)
from repair_assistant.semantic.pdf_extract import (
    outline_parts,
    page_count,
    write_pdf_part,
)
from repair_assistant.semantic.schema import REVIEW_FLAGS, SEGMENT_RESPONSE_FORMAT

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)

MODALITY_NATIVE_PDF = "native_pdf"
MODALITY_VISION = "vision"


class SegmenterClient(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        *,
        images: Any = None,
        pdf_path: Path | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class ProposedUnit:
    start_page: int
    end_page: int
    title: str
    unit_type: str
    rationale: str = ""
    review_flag: str = "none"
    review_note: str = ""
    start_y: float = 0.0
    end_y: float = 1.0


@dataclass
class Proposal:
    """What one segmentation run produced, kept verbatim for training data."""

    units: list[ProposedUnit] = field(default_factory=list)
    model: str = ""
    prompt_version: str = ""
    raw_output: str = ""
    llm_input: dict[str, Any] = field(default_factory=dict)
    windows: int = 0
    modality: str = MODALITY_NATIVE_PDF
    page_count: int = 0


class SegmentationError(RuntimeError):
    """The model returned something that is not a usable proposal."""


def choose_modality(
    pdf_path: Path,
    *,
    force_vision: bool | None = None,
    force_native: bool | None = None,
) -> str:
    if force_vision:
        return MODALITY_VISION
    if force_native:
        return MODALITY_NATIVE_PDF
    facts = inspect(pdf_path)
    if facts.looks_scanned:
        return MODALITY_VISION
    return MODALITY_NATIVE_PDF


def build_user_prompt(
    *,
    doc_title: str | None,
    part_title: str,
    start_page: int,
    end_page: int,
    window_index: int,
    window_count: int,
    modality: str,
) -> str:
    head = [f"Document: {doc_title}" if doc_title else "Document: (untitled)"]
    head.append(f"Part: {part_title}")
    if window_count > 1:
        head.append(
            f"Part {window_index} of {window_count}. Segment only pages "
            f"{start_page}-{end_page}; earlier and later parts are separate."
        )
    head.append(f"Pages in this part: {start_page}-{end_page} (1-based, inclusive).")
    if modality == MODALITY_VISION:
        head.append(
            "You are shown page images for this part. Propose contiguous units "
            "that cover every page in the range exactly once."
        )
    else:
        head.append(
            "You are given the PDF bytes for this part. Propose contiguous units "
            "that cover every page in the range exactly once."
        )
    head.append(
        "Each unit needs start_page, end_page, start_y, end_y (0.0=top of page, "
        "1.0=bottom), title, unit_type, rationale, review_flag, review_note. "
        "Never quote or rewrite source text."
    )
    return "\n".join(head)


def _normalise_review_flag(raw: object) -> str:
    flag = str(raw or "none").strip() or "none"
    if flag not in REVIEW_FLAGS:
        return "other"
    return flag


def _as_float(raw: object, default: float) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_proposal(raw: str) -> list[ProposedUnit]:
    """Parse the model's structured output. Shape errors are hard failures."""
    text = _FENCE.sub("", (raw or "").strip())
    if not text:
        raise SegmentationError("segmentation returned an empty response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SegmentationError(f"segmentation output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SegmentationError("segmentation output is not a JSON object")
    raw_units = payload.get("units")
    if not isinstance(raw_units, list):
        raise SegmentationError("segmentation output has no `units` array")

    units: list[ProposedUnit] = []
    for index, item in enumerate(raw_units):
        if not isinstance(item, dict):
            raise SegmentationError(f"unit {index} is not an object")
        try:
            start = int(item.get("start_page"))
            end = int(item.get("end_page"))
        except (TypeError, ValueError) as exc:
            raise SegmentationError(f"unit {index} has invalid pages") from exc
        flag = _normalise_review_flag(item.get("review_flag"))
        note = str(item.get("review_note") or "").strip()
        if flag == "none":
            note = ""
        units.append(
            ProposedUnit(
                start_page=start,
                end_page=end,
                start_y=_as_float(item.get("start_y"), 0.0),
                end_y=_as_float(item.get("end_y"), 1.0),
                title=str(item.get("title") or "").strip(),
                unit_type=str(item.get("unit_type") or "other").strip() or "other",
                rationale=str(item.get("rationale") or "").strip(),
                review_flag=flag,
                review_note=note,
            )
        )
    if not units:
        raise SegmentationError("segmentation proposed no units")
    return units


def build_client(*, model: str | None = None) -> SegmenterClient:
    """The curator-step OpenAI client. Only called by explicit operator actions."""
    from repair_assistant.qa.generate import OpenAIClient
    from repair_assistant.semantic.env import (
        semantic_llm_base_url,
        semantic_openai_api_key,
    )

    return OpenAIClient(
        api_key=semantic_openai_api_key(),
        model=model or semantic_llm_model(),
        prompt_name="semantic_segment",
        response_format=SEGMENT_RESPONSE_FORMAT,
        base_url=semantic_llm_base_url(),
    )


def _load_page_images(pdf_path: Path, doc_id: str, start_page: int, end_page: int):
    from repair_assistant.qa.page_images import PageImage, raster_pdf_page

    images: list[PageImage] = []
    cache_root = pdf_path.parent.parent / "parsed" / (doc_id or "_segment") / "page-rasters"
    for page in range(start_page, end_page + 1):
        cache = cache_root / f"p{page:04d}.jpg"
        jpeg = raster_pdf_page(pdf_path, page, cache)
        if not jpeg:
            raise SegmentationError(f"could not raster page {page} of {pdf_path}")
        images.append(
            PageImage(index=len(images) + 1, doc_id=doc_id, page=page, jpeg_bytes=jpeg)
        )
    return images


def propose_boundaries(
    pdf_path: Path,
    *,
    llm: SegmenterClient,
    doc_id: str = "",
    doc_title: str | None = None,
    model: str = "",
    force_vision: bool | None = None,
    force_native: bool | None = None,
    max_pages_per_part: int | None = None,
) -> Proposal:
    """Run segmentation over every PDF part and concatenate the proposals."""
    path = Path(pdf_path)
    if not path.is_file():
        raise SegmentationError(f"PDF not found: {path}")

    total = page_count(path)
    if total < 1:
        raise SegmentationError("PDF has no pages to segment")

    modality = choose_modality(
        path, force_vision=force_vision, force_native=force_native
    )
    budget = max_pages_per_part or segment_window_pages()
    parts = outline_parts(path, max_pages_per_part=budget)
    system = semantic_segment()
    units: list[ProposedUnit] = []
    raw_parts: list[str] = []
    prompts: list[str] = []
    part_meta: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="semantic-pdf-") as tmp:
        tmp_dir = Path(tmp)
        for index, part in enumerate(parts, start=1):
            user = build_user_prompt(
                doc_title=doc_title,
                part_title=part.title,
                start_page=part.start_page,
                end_page=part.end_page,
                window_index=index,
                window_count=len(parts),
                modality=modality,
            )
            prompts.append(user)
            part_meta.append(
                {
                    "title": part.title,
                    "start_page": part.start_page,
                    "end_page": part.end_page,
                    "modality": modality,
                }
            )
            if modality == MODALITY_VISION:
                if not doc_id:
                    raise SegmentationError(
                        "vision segmentation requires doc_id for page rasters"
                    )
                images = _load_page_images(
                    path, doc_id, part.start_page, part.end_page
                )
                raw = llm.complete(system, user, images=images)
            else:
                part_path = tmp_dir / f"part-{index:03d}.pdf"
                write_pdf_part(
                    path,
                    start_page=part.start_page,
                    end_page=part.end_page,
                    dest=part_path,
                )
                try:
                    raw = llm.complete(system, user, pdf_path=part_path)
                except TypeError:
                    # Test doubles that only accept (system, user).
                    raw = llm.complete(system, user)  # type: ignore[call-arg]
            raw_parts.append(raw)
            units.extend(parse_proposal(raw))

    return Proposal(
        units=units,
        model=model or semantic_llm_model(),
        prompt_version=prompt_digest("semantic_segment"),
        raw_output="\n".join(raw_parts),
        llm_input={
            "system": system,
            "windows": prompts,
            "parts": part_meta,
            "modality": modality,
            "page_count": total,
        },
        windows=len(parts),
        modality=modality,
        page_count=total,
    )
