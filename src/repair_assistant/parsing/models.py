"""Structured extract and chunk models for Phase 2 parsing.

These are deliberately separate from the corpus manifest: the manifest describes
documents; these describe what a parser recovered from their bytes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Block:
    """A contiguous text region on a page."""

    text: str
    page: int
    kind: str = "text"  # text | heading | list_item | warning
    bbox: BBox | None = None
    language: str | None = None


@dataclass
class TableRow:
    cells: list[str]
    page: int
    bbox: BBox | None = None


@dataclass
class Table:
    headers: list[str]
    rows: list[TableRow]
    page: int
    bbox: BBox | None = None


@dataclass
class ExtractedPage:
    number: int  # 1-based
    text: str
    blocks: list[Block] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    language: str | None = None


@dataclass
class ExtractedDocument:
    """Output of an extractor candidate."""

    path: str
    extractor: str
    pages: list[ExtractedPage]
    producer: str | None = None
    parse_audit: dict | None = None

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


@dataclass
class Chunk:
    """One retrieval unit derived from an ExtractedDocument."""

    chunk_id: str
    text: str
    page: int
    kind: str  # table_row | procedure | prose | heading | article
    error_codes: list[str] = field(default_factory=list)
    language: str | None = None
    doc_id: str | None = None
    publication_number: str | None = None
    revision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        import hashlib

        # Hash normalised text only so reflowed identical prose can match across
        # documents when we choose to compare that way.
        normalised = " ".join(self.text.split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["content_hash"] = self.content_hash()
        return data
