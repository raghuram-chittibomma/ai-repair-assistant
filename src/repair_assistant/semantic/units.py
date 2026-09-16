"""Assemble semantic knowledge units from PDF page-range markers (ADR-0049).

``source_text`` is a thin PDF extract of the unit's page range — never model
output and never hybrid-parse enrichment.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repair_assistant.semantic.pdf_extract import extract_page_range_text
from repair_assistant.semantic.validate import ValidatedSpan

_SLUG = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 48

REVIEW_PROPOSED = "proposed"
REVIEW_EDITED = "edited"
REVIEW_APPROVED = "approved"

ORIGIN_LLM = "llm"
ORIGIN_LLM_EDITED = "llm_edited"
ORIGIN_HUMAN = "human"


@dataclass
class SemanticUnit:
    unit_key: str
    ordinal: int
    title: str
    unit_type: str
    page_start: int | None
    page_end: int | None
    section_path: list[str]
    source_text: str
    source_span: list[str]
    content_hash: str
    review_status: str = REVIEW_PROPOSED
    origin: str = ORIGIN_LLM
    rationale: str = ""
    review_flag: str = "none"
    review_note: str = ""
    edits: list[dict[str, Any]] = field(default_factory=list)
    id: int | None = None
    start_y: float = 0.0
    end_y: float = 1.0
    needs_ocr: bool = False

    @property
    def page_label(self) -> str:
        if self.page_start is None:
            return ""
        if self.page_end is None or self.page_end == self.page_start:
            return f"p.{self.page_start}"
        return f"pp.{self.page_start}-{self.page_end}"

    @property
    def needs_review(self) -> bool:
        return (self.review_flag or "none") != "none" or self.needs_ocr

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_key": self.unit_key,
            "ordinal": self.ordinal,
            "title": self.title,
            "unit_type": self.unit_type,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "start_y": self.start_y,
            "end_y": self.end_y,
            "page_label": self.page_label,
            "section_path": list(self.section_path),
            "source_text": self.source_text,
            "source_span": list(self.source_span),
            "content_hash": self.content_hash,
            "review_status": self.review_status,
            "origin": self.origin,
            "rationale": self.rationale,
            "review_flag": self.review_flag or "none",
            "review_note": self.review_note,
            "needs_review": self.needs_review,
            "needs_ocr": self.needs_ocr,
            "edits": list(self.edits),
        }


def slugify(value: str, *, fallback: str = "unit") -> str:
    cleaned = _SLUG.sub("-", (value or "").strip().lower()).strip("-")
    return (cleaned[:_MAX_SLUG].strip("-") or fallback)


def marker_span_ids(
    start_page: int,
    end_page: int,
    *,
    start_y: float = 0.0,
    end_y: float = 1.0,
) -> list[str]:
    """Stable identity tags stored in ``source_span`` for hashing / edits."""
    return [
        f"p{int(start_page)}@{float(start_y):.4f}",
        f"p{int(end_page)}@{float(end_y):.4f}",
    ]


def content_hash(source_text: str, span_ids: list[str] | tuple[str, ...]) -> str:
    """Identity of a unit's content. Drives selective re-embedding."""
    material = "\n".join(span_ids) + "\n" + " ".join(source_text.split())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def assemble_source_text(
    pdf_path: Path,
    *,
    start_page: int,
    end_page: int,
) -> tuple[str, bool]:
    """Thin PDF extract for a page range. Second value is ``needs_ocr``."""
    text = extract_page_range_text(
        pdf_path, start_page=start_page, end_page=end_page
    )
    return text, not bool(text.strip())


def units_from_spans(
    spans: list[ValidatedSpan],
    *,
    pdf_path: Path,
    review_status: str = REVIEW_PROPOSED,
) -> list[SemanticUnit]:
    """Turn validated page spans into persistable units with stable keys."""
    ordered = sorted(spans, key=lambda s: (s.start_page, s.start_y, s.end_page))
    used: set[str] = set()
    units: list[SemanticUnit] = []

    for ordinal, span in enumerate(ordered):
        source_text, needs_ocr = assemble_source_text(
            pdf_path, start_page=span.start_page, end_page=span.end_page
        )
        span_ids = marker_span_ids(
            span.start_page,
            span.end_page,
            start_y=span.start_y,
            end_y=span.end_y,
        )
        base = slugify(span.title, fallback=slugify(span.unit_type, fallback="unit"))
        key = f"{ordinal + 1:03d}-{base}"
        suffix = 2
        while key in used:
            key = f"{ordinal + 1:03d}-{base}-{suffix}"
            suffix += 1
        used.add(key)

        units.append(
            SemanticUnit(
                unit_key=key,
                ordinal=ordinal,
                title=span.title or base.replace("-", " ").title(),
                unit_type=span.unit_type,
                page_start=span.start_page,
                page_end=span.end_page,
                section_path=list(span.section_path),
                source_text=source_text,
                source_span=span_ids,
                content_hash=content_hash(source_text, span_ids),
                review_status=review_status,
                origin=span.origin,
                rationale=span.rationale,
                review_flag=span.review_flag,
                review_note=span.review_note,
                start_y=span.start_y,
                end_y=span.end_y,
                needs_ocr=needs_ocr,
            )
        )
    return units


def resegment_unit(
    unit: SemanticUnit,
    *,
    pdf_path: Path,
    start_page: int,
    end_page: int,
    start_y: float = 0.0,
    end_y: float = 1.0,
    title: str | None = None,
    unit_type: str | None = None,
    origin: str = ORIGIN_LLM_EDITED,
) -> SemanticUnit:
    """Rebuild one unit over a new page range after a human edit."""
    if start_page > end_page:
        raise ValueError("a unit cannot end before it starts")
    source_text, needs_ocr = assemble_source_text(
        pdf_path, start_page=start_page, end_page=end_page
    )
    span_ids = marker_span_ids(
        start_page, end_page, start_y=start_y, end_y=end_y
    )
    return SemanticUnit(
        unit_key=unit.unit_key,
        ordinal=unit.ordinal,
        title=title if title is not None else unit.title,
        unit_type=unit_type if unit_type is not None else unit.unit_type,
        page_start=start_page,
        page_end=end_page,
        section_path=list(unit.section_path),
        source_text=source_text,
        source_span=span_ids,
        content_hash=content_hash(source_text, span_ids),
        review_status=REVIEW_EDITED,
        origin=origin,
        rationale=unit.rationale,
        review_flag=unit.review_flag,
        review_note=unit.review_note,
        edits=list(unit.edits),
        id=unit.id,
        start_y=start_y,
        end_y=end_y,
        needs_ocr=needs_ocr,
    )
