"""Request and response models for the corpus review API (ADR-0047, ADR-0048)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    version: int
    strategy: str
    status: str
    segmenter_model: str | None = None
    prompt_version: str | None = None
    created_at: str | None = None
    activated_at: str | None = None
    superseded_by: int | None = None


class CorpusDocumentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    doc_id: str
    title: str | None = None
    doc_type: str | None = None
    publication_number: str | None = None
    revision: str | None = None
    ingested: bool = False
    parsed: bool = False
    active_strategy: str | None = None
    active_version: int | None = None
    chunk_count: int = 0
    versions: list[VersionOut] = Field(default_factory=list)
    #: The semantic version shown on the review board: open candidate/ready,
    #: or the active semantic version when there is no open candidate.
    review_version: int | None = None
    review_status: str | None = None
    #: False when ``review_version`` is the live active set (read-only until Revise).
    review_editable: bool = False


class CorpusDocumentsResponse(BaseModel):
    documents: list[CorpusDocumentOut] = Field(default_factory=list)


class AnchorOut(BaseModel):
    anchor_id: str
    ordinal: int
    page: int | None = None
    kind: str | None = None
    section_path: list[str] = Field(default_factory=list)
    body: str
    unit_key: str | None = None
    #: Layout so the reviewer can see where a boundary falls on the page raster.
    bbox: dict[str, float] | None = None
    page_width: float | None = None
    page_height: float | None = None


class RepresentationOut(BaseModel):
    rep_kind: str
    text: str
    tokens: int | None = None
    over_limit: bool = False
    origin: str = "llm"
    embedded: bool = False


class UnitOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    unit_key: str
    ordinal: int
    title: str
    unit_type: str
    page_start: int | None = None
    page_end: int | None = None
    start_y: float = 0.0
    end_y: float = 1.0
    page_label: str = ""
    section_path: list[str] = Field(default_factory=list)
    source_text: str = ""
    source_span: list[str] = Field(default_factory=list)
    review_status: str = "proposed"
    origin: str = "llm"
    rationale: str = ""
    review_flag: str = "none"
    review_note: str = ""
    needs_review: bool = False
    needs_ocr: bool = False
    edits: list[dict[str, Any]] = Field(default_factory=list)
    representations: list[RepresentationOut] = Field(default_factory=list)
    representations_stale: bool = False
    #: Drafts that blew the token budget. Kept whole and unindexed so the
    #: reviewer can shorten them (ADR-0048: reject, never truncate).
    rejected_representations: list[RepresentationOut] = Field(default_factory=list)


class IssueOut(BaseModel):
    code: str
    detail: str
    unit_index: int | None = None


class SemanticVersionResponse(BaseModel):
    doc_id: str
    version: int
    strategy: str
    status: str
    segmenter_model: str | None = None
    prompt_version: str | None = None
    units: list[UnitOut] = Field(default_factory=list)
    anchors: list[AnchorOut] = Field(default_factory=list)
    issues: list[IssueOut] = Field(default_factory=list)
    ready_to_approve: bool = False
    token_budget: int = 0
    tokenizer_exact: bool = False
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    #: Vocabularies, so the review page follows the registry rather than
    #: hardcoding the kinds that happen to exist today (ADR-0048).
    unit_types: list[str] = Field(default_factory=list)
    representation_kinds: list[str] = Field(default_factory=list)
    review_flags: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    page_count: int | None = None


class ProposeRequest(BaseModel):
    repair_gaps: bool = Field(
        default=False,
        description=(
            "Attach pages the model left uncovered to the neighbouring unit. "
            "Recorded on the proposal as a repair; never silent."
        ),
    )
    skip_embed: bool = False


class ProposeResponse(BaseModel):
    doc_id: str
    status: str
    detail: str = ""
    version: int | None = None
    units: int = 0
    representations: int = 0
    embedded: int = 0
    over_limit: list[str] = Field(default_factory=list)
    issues: list[IssueOut] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)


class UnitPatchRequest(BaseModel):
    title: str | None = None
    unit_type: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    start_y: float | None = None
    end_y: float | None = None
    review_status: str | None = None
    #: Reviewer-authored representation text, keyed by kind.
    representations: dict[str, str] | None = None
    regenerate_representations: bool = False


class UnitSplitRequest(BaseModel):
    at_page: int
    at_y: float = 0.0
    title: str | None = None


class UnitMergeRequest(BaseModel):
    #: ``next``, ``previous``, or an explicit unit key.
    with_unit: str = "next"
    title: str | None = None


class UnitAddRequest(BaseModel):
    start_page: int
    end_page: int
    title: str
    unit_type: str = "other"
    start_y: float = 0.0
    end_y: float = 1.0


class EditResponse(BaseModel):
    doc_id: str
    version: int
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    re_embedded: int = 0
    issues: list[IssueOut] = Field(default_factory=list)
    ready_to_approve: bool = False
    over_limit: list[str] = Field(default_factory=list)


class VersionActionResponse(BaseModel):
    doc_id: str
    version: int
    status: str
    strategy: str
    detail: str = ""
    active_version: int | None = None
    active_strategy: str | None = None


class RevertRequest(BaseModel):
    version: int | None = Field(
        default=None,
        description="Version to activate. Defaults to the latest structured version.",
    )
