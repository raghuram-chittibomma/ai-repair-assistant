"""The curator step: propose â†’ validate â†’ units; then review; then index.

Lifecycle (ADR-0049):

  PDF-native semantic segmentation (native PDF or vision when scanned)
      â†’ human review / boundary correction on the real PDF
      â†’ approved semantic units (thin PDF extract as source_text)
      â†’ retrieval representation generation
      â†’ embedding / indexing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.prompts import prompt_digest
from repair_assistant.semantic import store as semantic_store
from repair_assistant.semantic.lifecycle import (
    STATUS_CANDIDATE,
    STATUS_READY,
    STATUS_SUPERSEDED,
    STRATEGY_SEMANTIC,
    IngestionVersion,
    LifecycleError,
    create_candidate,
    latest_semantic_version,
    list_versions,
)
from repair_assistant.semantic.representations import (
    RepresentationClient,
    RepresentationSet,
    generate_representations,
)
from repair_assistant.semantic.segment import (
    SegmenterClient,
    propose_boundaries,
)
from repair_assistant.semantic.units import SemanticUnit, units_from_spans
from repair_assistant.semantic.validate import ValidationReport, absorb_gaps, validate

if TYPE_CHECKING:
    from repair_assistant.ingest.embeddings import Embedder
    from repair_assistant.ingest.store import Database

STATUS_PROPOSED = "proposed"
STATUS_REJECTED = "rejected"


@dataclass
class CurateResult:
    doc_id: str
    status: str
    detail: str = ""
    version: IngestionVersion | None = None
    units: list[SemanticUnit] = field(default_factory=list)
    report: ValidationReport | None = None
    indexed: int = 0
    embedded: int = 0
    over_limit: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PROPOSED


def propose_semantic_version(
    db: Database,
    *,
    doc_id: str,
    pdf_path: Path,
    segmenter: SegmenterClient,
    representer: RepresentationClient | None = None,
    embedder: Embedder | None = None,
    doc_title: str | None = None,
    publication_number: str | None = None,
    revision: str | None = None,
    repair_gaps: bool = False,
    generate_representations: bool = False,
    force_vision: bool | None = None,
    force_native: bool | None = None,
    source_fingerprint: str = "",
) -> CurateResult:
    """Open a candidate semantic version from the manufacturer PDF.

    By default this stops after validated units are stored. Pass
    ``generate_representations=True`` only for CLI convenience paths that skip the
    review board; the UI deferral is the preferred lifecycle.
    """
    path = Path(pdf_path)
    if not path.is_file():
        return CurateResult(
            doc_id=doc_id,
            status=STATUS_REJECTED,
            detail=f"PDF not found: {path}",
        )

    existing = latest_semantic_version(db, doc_id)
    if existing is not None and existing.status in {STATUS_CANDIDATE, STATUS_READY}:
        raise LifecycleError(
            f"{doc_id}: version {existing.version} is already an open candidate. "
            "Approve, activate, or abandon it before proposing another."
        )

    version = create_candidate(
        db,
        doc_id,
        strategy=STRATEGY_SEMANTIC,
        source_fingerprint=source_fingerprint or path.name,
        prompt_version=prompt_digest("semantic_segment"),
        meta={"pdf": str(path.name)},
    )
    db.commit()

    proposal = propose_boundaries(
        path,
        llm=segmenter,
        doc_id=doc_id,
        doc_title=doc_title,
        force_vision=force_vision,
        force_native=force_native,
    )
    db.execute(
        "UPDATE ingestion_versions SET segmenter_model = %s, meta = meta || %s::jsonb WHERE id = %s",
        (
            proposal.model,
            __import__("json").dumps(
                {
                    "modality": proposal.modality,
                    "page_count": proposal.page_count,
                    "windows": proposal.windows,
                }
            ),
            version.id,
        ),
    )

    report = validate(
        proposal.units,
        window_start=1,
        window_end=proposal.page_count,
    )
    if repair_gaps and not report.ok:
        report = absorb_gaps(
            report, window_start=1, window_end=proposal.page_count
        )

    semantic_store.record_proposal(
        db,
        version.id,
        model=proposal.model,
        prompt_version=proposal.prompt_version,
        llm_input=proposal.llm_input,
        raw_output=proposal.raw_output,
        validation=report.to_json(),
    )

    if not report.ok:
        db.commit()
        return CurateResult(
            doc_id=doc_id,
            status=STATUS_REJECTED,
            detail="; ".join(f"{i.code}: {i.detail}" for i in report.issues),
            version=version,
            report=report,
        )

    units = semantic_store.replace_units(
        db, version.id, units_from_spans(report.spans, pdf_path=path)
    )
    indexed = embedded = 0
    over_limit: list[str] = []
    if generate_representations:
        if representer is None or embedder is None:
            raise ValueError(
                "generate_representations=True requires both a representer and an embedder"
            )
        indexed, embedded, over_limit = index_version_representations(
            db,
            doc_id=doc_id,
            version_id=version.id,
            units=units,
            representer=representer,
            embedder=embedder,
            publication_number=publication_number,
            revision=revision,
        )
    db.commit()

    detail = f"{len(units)} units ({proposal.modality})"
    if generate_representations:
        detail += f", {indexed} representations"
    else:
        detail += "; representations deferred until approve"

    return CurateResult(
        doc_id=doc_id,
        status=STATUS_PROPOSED,
        detail=detail,
        version=version,
        units=units,
        report=report,
        indexed=indexed,
        embedded=embedded,
        over_limit=over_limit,
    )


def index_version_representations(
    db: Database,
    *,
    doc_id: str,
    version_id: int,
    units: list[SemanticUnit] | None = None,
    representer: RepresentationClient,
    embedder: Embedder,
    publication_number: str | None = None,
    revision: str | None = None,
) -> tuple[int, int, list[str]]:
    """Generate and embed retrieval representations for every unit in a version."""
    target = units if units is not None else semantic_store.list_units(db, version_id)
    return _index_units(
        db,
        doc_id=doc_id,
        version_id=version_id,
        units=target,
        representer=representer,
        embedder=embedder,
        publication_number=publication_number,
        revision=revision,
    )


def _index_units(
    db: Database,
    *,
    doc_id: str,
    version_id: int,
    units: list[SemanticUnit],
    representer: RepresentationClient,
    embedder: Embedder,
    publication_number: str | None,
    revision: str | None,
) -> tuple[int, int, list[str]]:
    indexed = 0
    over_limit: list[str] = []
    for unit in units:
        rep_set = generate_representations(unit, llm=representer)
        over_limit.extend(
            f"{unit.unit_key}:{r.rep_kind}" for r in rep_set.over_limit
        )
        indexed += semantic_store.write_representations(
            db,
            doc_id=doc_id,
            version_id=version_id,
            unit=unit,
            representations=rep_set.representations,
            publication_number=publication_number,
            revision=revision,
            error_codes=extract_error_codes(unit.source_text),
        )
    stats = semantic_store.embed_missing(
        db, doc_id, version_id=version_id, embedder=embedder
    )
    return indexed, stats.embedded, over_limit


def regenerate_unit_representations(
    db: Database,
    *,
    doc_id: str,
    version_id: int,
    unit: SemanticUnit,
    representer: RepresentationClient,
    embedder: Embedder,
    publication_number: str | None = None,
    revision: str | None = None,
) -> RepresentationSet:
    """Re-run representation generation for one unit after a boundary edit."""
    rep_set = generate_representations(unit, llm=representer)
    semantic_store.write_representations(
        db,
        doc_id=doc_id,
        version_id=version_id,
        unit=unit,
        representations=rep_set.representations,
        publication_number=publication_number,
        revision=revision,
        error_codes=extract_error_codes(unit.source_text),
    )
    stats = semantic_store.embed_missing(
        db, doc_id, version_id=version_id, embedder=embedder
    )
    rep_set.embedded = stats.embedded
    return rep_set


def version_summary(db: Database, doc_id: str) -> list[dict]:
    """Version history for the document-management view."""
    return [
        {
            "id": v.id,
            "version": v.version,
            "strategy": v.strategy,
            "status": v.status,
            "segmenter_model": v.segmenter_model,
            "prompt_version": v.prompt_version,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "activated_at": v.activated_at.isoformat() if v.activated_at else None,
            "superseded_by": v.superseded_by,
        }
        for v in list_versions(db, doc_id)
    ]


def fork_semantic_candidate(
    db: Database,
    doc_id: str,
    *,
    source_version: int | None = None,
) -> IngestionVersion:
    """Clone live (or given) semantic units into a new editable candidate.

    The active version keeps serving traffic until the candidate is finalized
    and activated again (ADR-0047).
    """
    from dataclasses import replace

    from repair_assistant.semantic.lifecycle import (
        STATUS_ACTIVE,
        active_version,
        get_version,
    )

    open_pending = [
        v
        for v in list_versions(db, doc_id)
        if v.strategy == STRATEGY_SEMANTIC and v.status in {STATUS_CANDIDATE, STATUS_READY}
    ]
    if open_pending:
        raise LifecycleError(
            f"{doc_id}: version {open_pending[0].version} is already an open "
            f"{open_pending[0].status}. Finish or abandon it before revising."
        )

    if source_version is not None:
        source = get_version(db, doc_id, source_version)
        if source is None:
            raise LifecycleError(f"{doc_id}: no version {source_version}")
    else:
        source = active_version(db, doc_id)
    if source is None or source.strategy != STRATEGY_SEMANTIC:
        raise LifecycleError(
            f"{doc_id}: no active semantic version to revise. Propose semantic first."
        )
    if source.status in {STATUS_CANDIDATE, STATUS_READY}:
        raise LifecycleError(
            f"{doc_id}: version {source.version} is already editable ({source.status})"
        )
    if source.status not in {STATUS_ACTIVE, STATUS_SUPERSEDED}:
        raise LifecycleError(
            f"{doc_id}: version {source.version} is {source.status}; cannot revise from it"
        )

    units = semantic_store.list_units(db, source.id)
    if not units:
        raise LifecycleError(f"{doc_id}: version {source.version} has no units to clone")

    candidate = create_candidate(
        db,
        doc_id,
        strategy=STRATEGY_SEMANTIC,
        source_fingerprint=source.source_fingerprint,
        segmenter_model=source.segmenter_model,
        prompt_version=source.prompt_version,
        meta={"forked_from": source.version},
    )
    clones = [
        replace(
            unit,
            id=None,
            edits=[
                *unit.edits,
                {
                    "action": "fork",
                    "from_version": source.version,
                },
            ],
        )
        for unit in units
    ]
    semantic_store.replace_units(db, candidate.id, clones)
    db.commit()
    refreshed = latest_semantic_version(db, doc_id)
    if refreshed is None:  # pragma: no cover
        raise LifecycleError(f"{doc_id}: fork vanished after commit")
    return refreshed
