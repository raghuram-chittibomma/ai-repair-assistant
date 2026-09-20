"""`/v1/corpus/*` — document ingestion strategy and semantic boundary review.

A separate router from the chat API because it is a different task and a
different person: the reviewer works against the real PDF and page-range
markers, not against answers. Mounted behind the same API key as everything else.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from repair_assistant.api.assist_sessions import AssistSessionStore
from repair_assistant.api.corpus_schemas import (
    AssistMessageRequest,
    AssistMessageResponse,
    AssistSessionCreateRequest,
    AssistSessionOut,
    AssistSuggestionOut,
    CorpusDocumentOut,
    CorpusDocumentsResponse,
    EditResponse,
    IssueOut,
    ProposeRequest,
    ProposeResponse,
    RevertRequest,
    SemanticVersionResponse,
    UnitAddRequest,
    UnitMergeRequest,
    UnitOut,
    UnitPatchRequest,
    UnitSplitRequest,
    VersionActionResponse,
    VersionOut,
)
from repair_assistant.ingest.store import Database
from repair_assistant.qa.page_images import document_pdf_path
from repair_assistant.semantic import review as review_mod
from repair_assistant.semantic import store as semantic_store
from repair_assistant.semantic.curate import (
    fork_semantic_candidate,
    index_version_representations,
    propose_semantic_version,
    regenerate_unit_representations,
)
from repair_assistant.semantic.lifecycle import (
    STATUS_CANDIDATE,
    STATUS_READY,
    STRATEGY_SEMANTIC,
    STRATEGY_STRUCTURED,
    IngestionVersion,
    LifecycleError,
    activate,
    active_version,
    get_version,
    list_versions,
    mark_ready,
    revert_to,
)
from repair_assistant.semantic.pdf_extract import page_count as pdf_page_count
from repair_assistant.semantic.representations import BUILDERS, edited_representation
from repair_assistant.semantic.schema import REVIEW_FLAGS, UNIT_TYPES
from repair_assistant.semantic.tokens import DEFAULT_TOKEN_BUDGET, tokenizer_is_exact
from repair_assistant.semantic.units import SemanticUnit


def _issues(report) -> list[IssueOut]:
    return [IssueOut(**i.to_json()) for i in report.issues]


def _looks_like_pdf(path: Path) -> bool:
    """True when the file starts with the PDF magic header."""
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _version_out(version: IngestionVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        version=version.version,
        strategy=version.strategy,
        status=version.status,
        segmenter_model=version.segmenter_model,
        prompt_version=version.prompt_version,
        created_at=version.created_at.isoformat() if version.created_at else None,
        activated_at=version.activated_at.isoformat() if version.activated_at else None,
        superseded_by=version.superseded_by,
    )


def build_corpus_router(
    *,
    get_db: Callable[..., Any],
    require_api_key: Callable[..., Any],
    manifest: Callable[[], Any],
    repo_root: Callable[[], Any],
    embedder: Callable[[], Any],
    segmenter: Callable[[], Any] | None = None,
    representer: Callable[[], Any] | None = None,
    assist_store: AssistSessionStore | None = None,
    assist_client: Callable[[], Any] | None = None,
) -> APIRouter:
    """Build the router. Collaborators are injected so tests can fake the LLM."""
    router = APIRouter(
        prefix="/v1/corpus",
        tags=["corpus"],
        dependencies=[Depends(require_api_key)],
    )
    sessions = assist_store or AssistSessionStore()

    def _parsed_dir(doc_id: str):
        return repo_root() / "corpus" / "parsed" / doc_id

    def _pdf_path(doc_id: str) -> Path:
        from pathlib import Path

        path = document_pdf_path(manifest(), doc_id)
        if path is None:
            # Resolve via publication number alias
            document = _manifest_document(doc_id)
            if document is not None:
                path = document_pdf_path(manifest(), document.doc_id)
        if path is None or not Path(path).is_file():
            raise HTTPException(
                status_code=409,
                detail=f"{doc_id}: PDF not found under corpus/documents/",
            )
        resolved = Path(path)
        # KB saves are often .mhtml; PDF.js hangs if we stream those as PDFs.
        if resolved.suffix.lower() != ".pdf" or not _looks_like_pdf(resolved):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{doc_id}: corpus file is {resolved.name}, not a PDF. "
                    "Semantic review needs a manufacturer PDF under corpus/documents/."
                ),
            )
        return resolved

    def _page_window(doc_id: str) -> tuple[int, int]:
        total = pdf_page_count(_pdf_path(doc_id))
        return 1, total

    def _manifest_document(doc_id: str):
        for doc in manifest().documents:
            if doc.doc_id == doc_id or doc.publication_number == doc_id:
                return doc
        return None

    def _semantic_version(db: Database, doc_id: str, version: int) -> IngestionVersion:
        found = get_version(db, doc_id, version)
        if found is None:
            raise HTTPException(status_code=404, detail=f"{doc_id}: no version {version}")
        if found.strategy != STRATEGY_SEMANTIC:
            raise HTTPException(
                status_code=409,
                detail=f"{doc_id}: version {version} is {found.strategy}, not semantic",
            )
        return found

    def _editable(db: Database, doc_id: str, version: int) -> IngestionVersion:
        found = _semantic_version(db, doc_id, version)
        if found.status not in {STATUS_CANDIDATE, STATUS_READY}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{doc_id}: version {version} is {found.status}. "
                    "Click Revise to open an editable candidate copy "
                    "(the live version keeps serving until you Finalize + Activate)."
                ),
            )
        return found

    def _unit(db: Database, version_id: int, unit_key: str) -> SemanticUnit:
        found = semantic_store.get_unit(db, version_id, unit_key)
        if found is None:
            raise HTTPException(status_code=404, detail=f"{unit_key}: no such unit")
        return found

    def _requires_llm(factory: Callable[[], Any] | None, what: str):
        if factory is None:
            raise HTTPException(
                status_code=503,
                detail=f"{what} is not configured on this server",
            )
        try:
            return factory()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _edit_response(
        db: Database,
        doc_id: str,
        version: IngestionVersion,
        outcome: review_mod.EditOutcome,
        *,
        re_embedded: int = 0,
        over_limit: list[str] | None = None,
    ) -> EditResponse:
        db.commit()
        units = semantic_store.list_units(db, version.id)
        start, end = _page_window(doc_id)
        report = review_mod.review_issues(units, window_start=start, window_end=end)
        return EditResponse(
            doc_id=doc_id,
            version=version.version,
            changed=outcome.changed_keys,
            removed=list(outcome.removed),
            re_embedded=re_embedded,
            issues=_issues(report),
            ready_to_approve=report.ok
            and semantic_store.all_units_approved(db, version.id),
            over_limit=list(over_limit or []),
        )

    # --- document list -----------------------------------------------------

    @router.get("/documents", response_model=CorpusDocumentsResponse)
    def list_documents(db: Database = Depends(get_db)) -> CorpusDocumentsResponse:
        rows = {
            str(r[0]): int(r[1] or 0)
            for r in db.fetchall("SELECT doc_id, chunk_count FROM documents")
        }
        out: list[CorpusDocumentOut] = []
        for doc in sorted(manifest().documents, key=lambda d: (d.doc_type, d.doc_id)):
            versions = list_versions(db, doc.doc_id)
            active = next((v for v in versions if v.status == "active"), None)
            pending = next(
                (
                    v
                    for v in versions
                    if v.strategy == STRATEGY_SEMANTIC
                    and v.status in {STATUS_CANDIDATE, STATUS_READY}
                ),
                None,
            )
            # Prefer an open candidate; otherwise show the live semantic markers.
            board = pending
            if board is None and active is not None and active.strategy == STRATEGY_SEMANTIC:
                board = active
            out.append(
                CorpusDocumentOut(
                    doc_id=doc.doc_id,
                    title=doc.title,
                    doc_type=doc.doc_type,
                    publication_number=doc.publication_number,
                    revision=doc.revision,
                    ingested=doc.doc_id in rows,
                    parsed=(_parsed_dir(doc.doc_id) / "chunks.jsonl").is_file(),
                    active_strategy=active.strategy if active else None,
                    active_version=active.version if active else None,
                    chunk_count=rows.get(doc.doc_id, 0),
                    versions=[_version_out(v) for v in versions],
                    review_version=board.version if board else None,
                    review_status=board.status if board else None,
                    review_editable=bool(
                        board and board.status in {STATUS_CANDIDATE, STATUS_READY}
                    ),
                )
            )
        return CorpusDocumentsResponse(documents=out)

    # --- propose -----------------------------------------------------------

    @router.post(
        "/documents/{doc_id}/semantic/propose",
        response_model=ProposeResponse,
    )
    def propose(
        doc_id: str,
        body: ProposeRequest | None = None,
        db: Database = Depends(get_db),
    ) -> ProposeResponse:
        """The "Process with Semantic Ingestion" action. Costs OpenAI tokens.

        Segmentation only. Retrieval representations are generated later, when
        the reviewer approves the units â€” so a split or merge does not throw
        away paid summaries.
        """
        request = body or ProposeRequest()
        document = _manifest_document(doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"{doc_id}: no manifest entry")
        pdf = _pdf_path(document.doc_id)

        try:
            result = propose_semantic_version(
                db,
                doc_id=document.doc_id,
                pdf_path=pdf,
                segmenter=_requires_llm(segmenter, "semantic segmentation"),
                doc_title=document.title,
                publication_number=document.publication_number,
                revision=document.revision,
                repair_gaps=request.repair_gaps,
                generate_representations=False,
            )
        except LifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return ProposeResponse(
            doc_id=result.doc_id,
            status=result.status,
            detail=result.detail,
            version=result.version.version if result.version else None,
            units=len(result.units),
            representations=result.indexed,
            embedded=result.embedded,
            over_limit=list(result.over_limit),
            issues=_issues(result.report) if result.report else [],
            repairs=list(result.report.repairs) if result.report else [],
        )

    @router.post(
        "/documents/{doc_id}/semantic/revise",
        response_model=ProposeResponse,
    )
    def revise(
        doc_id: str,
        db: Database = Depends(get_db),
    ) -> ProposeResponse:
        """Clone the live semantic markers into a new editable candidate."""
        document = _manifest_document(doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"{doc_id}: no manifest entry")
        try:
            candidate = fork_semantic_candidate(db, document.doc_id)
        except LifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        units = semantic_store.list_units(db, candidate.id)
        return ProposeResponse(
            doc_id=document.doc_id,
            status="candidate",
            detail=(
                f"Opened editable candidate v{candidate.version} "
                f"({len(units)} units cloned). Live retrieval is unchanged until "
                "you Finalize and Activate."
            ),
            version=candidate.version,
            units=len(units),
        )

    # --- review ------------------------------------------------------------

    @router.get(
        "/documents/{doc_id}/semantic/versions/{version}",
        response_model=SemanticVersionResponse,
    )
    def get_semantic_version(
        doc_id: str,
        version: int,
        db: Database = Depends(get_db),
    ) -> SemanticVersionResponse:
        found = _semantic_version(db, doc_id, version)
        payload = semantic_store.units_with_representations(db, found.id)
        units = semantic_store.list_units(db, found.id)
        start_page, end_page = _page_window(doc_id)
        report = review_mod.review_issues(
            units, window_start=start_page, window_end=end_page
        )

        return SemanticVersionResponse(
            doc_id=doc_id,
            version=found.version,
            strategy=found.strategy,
            status=found.status,
            segmenter_model=found.segmenter_model,
            prompt_version=found.prompt_version,
            units=[
                UnitOut(
                    **{
                        **item,
                        "representations_stale": item.get(
                            "representations_stale",
                            item.get("reps_stale", False),
                        ),
                    }
                )
                for item in payload
            ],
            anchors=[],
            issues=_issues(report),
            ready_to_approve=report.ok
            and semantic_store.all_units_approved(db, found.id),
            token_budget=DEFAULT_TOKEN_BUDGET,
            tokenizer_exact=tokenizer_is_exact(),
            proposals=semantic_store.list_proposals(db, found.id),
            unit_types=list(UNIT_TYPES),
            representation_kinds=list(BUILDERS),
            review_flags=list(REVIEW_FLAGS),
            pdf_url=f"/v1/corpus/documents/{doc_id}/pdf",
            page_count=_page_window(doc_id)[1],
        )

    @router.get("/documents/{doc_id}/semantic/versions/{version}/training-export")
    def training_export(
        doc_id: str,
        version: int,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        """Proposal, corrections, and approved result â€” the training trail."""
        found = _semantic_version(db, doc_id, version)
        export = semantic_store.training_export(db, found.id)
        export["doc_id"] = doc_id
        export["version"] = found.version
        return export

    # --- unit edits --------------------------------------------------------

    def _regenerate(
        db: Database,
        doc_id: str,
        version: IngestionVersion,
        units: list[SemanticUnit],
    ) -> tuple[int, list[str]]:
        document = _manifest_document(doc_id)
        client = _requires_llm(representer, "representation generation")
        shared = embedder()
        over: list[str] = []
        touched = 0
        for unit in units:
            if unit.id is None:
                refreshed = semantic_store.get_unit(db, version.id, unit.unit_key)
                if refreshed is None:
                    continue
                unit = refreshed
            rep_set = regenerate_unit_representations(
                db,
                doc_id=doc_id,
                version_id=version.id,
                unit=unit,
                representer=client,
                embedder=shared,
                publication_number=document.publication_number if document else None,
                revision=document.revision if document else None,
            )
            over.extend(f"{unit.unit_key}:{r.rep_kind}" for r in rep_set.over_limit)
            touched += rep_set.embedded
        return touched, over

    @router.patch(
        "/documents/{doc_id}/semantic/versions/{version}/units/{unit_key}",
        response_model=EditResponse,
    )
    def patch_unit(
        doc_id: str,
        version: int,
        unit_key: str,
        body: UnitPatchRequest,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        unit = _unit(db, found.id, unit_key)
        changed: list[SemanticUnit] = []
        removed: list[str] = []
        over: list[str] = []
        re_embedded = 0

        try:
            if any(
                value is not None
                for value in (
                    body.start_page,
                    body.end_page,
                    body.start_y,
                    body.end_y,
                )
            ):
                outcome = review_mod.resize_unit_pushing_neighbors(
                    db,
                    found.id,
                    unit,
                    pdf_path=_pdf_path(doc_id),
                    start_page=body.start_page,
                    end_page=body.end_page,
                    start_y=body.start_y,
                    end_y=body.end_y,
                    title=body.title,
                    unit_type=body.unit_type,
                )
                changed.extend(outcome.changed)
                removed.extend(outcome.removed)
                if outcome.changed:
                    unit = next(
                        (u for u in outcome.changed if u.unit_key == unit_key),
                        outcome.changed[0],
                    )
            elif body.title is not None or body.unit_type is not None:
                outcome = review_mod.move_boundary(
                    db,
                    found.id,
                    unit,
                    pdf_path=_pdf_path(doc_id),
                    title=body.title,
                    unit_type=body.unit_type,
                )
                changed.extend(outcome.changed)
                removed.extend(outcome.removed)
                if outcome.changed:
                    unit = outcome.changed[0]

            if body.representations:
                reps = [
                    edited_representation(unit.unit_key, kind, text)
                    for kind, text in body.representations.items()
                ]
                document = _manifest_document(doc_id)
                semantic_store.write_representations(
                    db,
                    doc_id=doc_id,
                    version_id=found.id,
                    unit=unit,
                    representations=reps,
                    publication_number=document.publication_number if document else None,
                    revision=document.revision if document else None,
                    prune=False,
                )
                over.extend(f"{unit.unit_key}:{r.rep_kind}" for r in reps if r.over_limit)
                stats = semantic_store.embed_missing(
                    db, doc_id, version_id=found.id, embedder=embedder()
                )
                re_embedded += stats.embedded
                if unit not in changed:
                    changed.append(unit)

            if body.regenerate_representations and unit.id is not None:
                touched, flagged = _regenerate(db, doc_id, found, [unit])
                re_embedded += touched
                over.extend(flagged)

            if body.review_status is not None:
                outcome = review_mod.set_review_status(
                    db, found.id, unit, body.review_status
                )
                changed.extend(u for u in outcome.changed if u not in changed)
        except review_mod.ReviewError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return _edit_response(
            db,
            doc_id,
            found,
            review_mod.EditOutcome(changed=changed, removed=removed),
            re_embedded=re_embedded,
            over_limit=over,
        )

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/units/{unit_key}/split",
        response_model=EditResponse,
    )
    def split_unit(
        doc_id: str,
        version: int,
        unit_key: str,
        body: UnitSplitRequest,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        unit = _unit(db, found.id, unit_key)
        try:
            outcome = review_mod.split_unit(
                db,
                found.id,
                unit,
                pdf_path=_pdf_path(doc_id),
                at_page=body.at_page,
                at_y=body.at_y,
                title=body.title,
            )
        except review_mod.ReviewError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _edit_response(db, doc_id, found, outcome)

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/units/{unit_key}/merge",
        response_model=EditResponse,
    )
    def merge_unit(
        doc_id: str,
        version: int,
        unit_key: str,
        body: UnitMergeRequest,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        units = semantic_store.list_units(db, found.id)
        by_key = {u.unit_key: u for u in units}
        if unit_key not in by_key:
            raise HTTPException(status_code=404, detail=f"{unit_key}: no such unit")
        position = [u.unit_key for u in units].index(unit_key)

        if body.with_unit == "next":
            other = units[position + 1] if position + 1 < len(units) else None
        elif body.with_unit == "previous":
            other = units[position - 1] if position > 0 else None
        else:
            other = by_key.get(body.with_unit)
        if other is None:
            raise HTTPException(
                status_code=422, detail=f"{unit_key}: no {body.with_unit} unit to merge with"
            )

        try:
            outcome = review_mod.merge_units(
                db,
                found.id,
                by_key[unit_key],
                other,
                pdf_path=_pdf_path(doc_id),
                title=body.title,
            )
        except review_mod.ReviewError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _edit_response(db, doc_id, found, outcome)

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/units",
        response_model=EditResponse,
    )
    def add_unit(
        doc_id: str,
        version: int,
        body: UnitAddRequest,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        try:
            outcome = review_mod.add_unit(
                db,
                found.id,
                pdf_path=_pdf_path(doc_id),
                start_page=body.start_page,
                end_page=body.end_page,
                start_y=body.start_y,
                end_y=body.end_y,
                title=body.title,
                unit_type=body.unit_type,
            )
        except review_mod.ReviewError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _edit_response(db, doc_id, found, outcome)

    @router.delete(
        "/documents/{doc_id}/semantic/versions/{version}/units/{unit_key}",
        response_model=EditResponse,
    )
    def delete_unit(
        doc_id: str,
        version: int,
        unit_key: str,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        unit = _unit(db, found.id, unit_key)
        outcome = review_mod.remove_unit(db, found.id, unit)
        return _edit_response(db, doc_id, found, outcome)

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}"
        "/units/{unit_key}/representations/regenerate",
        response_model=EditResponse,
    )
    def regenerate_representations(
        doc_id: str,
        version: int,
        unit_key: str,
        db: Database = Depends(get_db),
    ) -> EditResponse:
        found = _editable(db, doc_id, version)
        unit = _unit(db, found.id, unit_key)
        touched, over = _regenerate(db, doc_id, found, [unit])
        return _edit_response(
            db,
            doc_id,
            found,
            review_mod.EditOutcome(changed=[unit], removed=[]),
            re_embedded=touched,
            over_limit=over,
        )

    # --- version actions ---------------------------------------------------

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/approve",
        response_model=VersionActionResponse,
    )
    def approve(
        doc_id: str,
        version: int,
        db: Database = Depends(get_db),
    ) -> VersionActionResponse:
        """Mark a reviewed version ready, generating representations first.

        Representations are produced here â€” after the reviewer has settled the
        boundaries â€” so split/merge work does not waste summary tokens.
        """
        found = _editable(db, doc_id, version)
        units = semantic_store.list_units(db, found.id)
        start, end = _page_window(doc_id)
        report = review_mod.approve_version_preflight(
            units, window_start=start, window_end=end
        )
        if not report.ok:
            raise HTTPException(
                status_code=422,
                detail="; ".join(f"{i.code}: {i.detail}" for i in report.issues),
            )
        document = _manifest_document(doc_id)
        indexed, embedded, over = index_version_representations(
            db,
            doc_id=doc_id,
            version_id=found.id,
            units=units,
            representer=_requires_llm(representer, "representation generation"),
            embedder=embedder(),
            publication_number=document.publication_number if document else None,
            revision=document.revision if document else None,
        )
        if over:
            raise HTTPException(
                status_code=422,
                detail=(
                    "representation(s) still over the token budget after regenerate: "
                    + ", ".join(over)
                    + ". Shorten them in the review board, then approve again."
                ),
            )
        for unit in units:
            if unit.review_status != "approved":
                review_mod.set_review_status(db, found.id, unit, "approved")
        db.commit()
        ready = mark_ready(db, found.id)
        current = active_version(db, doc_id)
        return VersionActionResponse(
            doc_id=doc_id,
            version=ready.version,
            status=ready.status,
            strategy=ready.strategy,
            detail=(
                f"{len(units)} units approved; {indexed} representations "
                f"({embedded} embedded); activate to cut over"
            ),
            active_version=current.version if current else None,
            active_strategy=current.strategy if current else None,
        )

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/activate",
        response_model=VersionActionResponse,
    )
    def activate_version(
        doc_id: str,
        version: int,
        db: Database = Depends(get_db),
    ) -> VersionActionResponse:
        """Atomic cutover: this version active, the previous one superseded."""
        found = _semantic_version(db, doc_id, version)
        rep_rows = db.fetchone(
            """
            SELECT
                count(*) FILTER (WHERE unit_id IS NOT NULL),
                count(*) FILTER (WHERE unit_id IS NOT NULL AND embedding IS NULL)
            FROM chunks
            WHERE ingestion_version_id = %s
            """,
            (found.id,),
        )
        indexed = int(rep_rows[0]) if rep_rows else 0
        missing = int(rep_rows[1]) if rep_rows else 0
        if indexed == 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{doc_id}: no retrieval representations yet. "
                    "Approve the version (which generates them) before cutting over."
                ),
            )
        if missing > 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{doc_id}: {missing} representation(s) have no vector. "
                    "Regenerate them before cutting over."
                ),
            )
        try:
            live = activate(db, found.id)
        except LifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return VersionActionResponse(
            doc_id=doc_id,
            version=live.version,
            status=live.status,
            strategy=live.strategy,
            detail="cutover complete; the previous version is superseded",
            active_version=live.version,
            active_strategy=live.strategy,
        )

    @router.post("/documents/{doc_id}/revert", response_model=VersionActionResponse)
    def revert(
        doc_id: str,
        body: RevertRequest | None = None,
        db: Database = Depends(get_db),
    ) -> VersionActionResponse:
        """Activate an earlier version. A rollback, not a re-parse."""
        request = body or RevertRequest()
        versions = list_versions(db, doc_id)
        if not versions:
            raise HTTPException(status_code=404, detail=f"{doc_id}: no ingestion versions")
        target = request.version
        if target is None:
            structured = [
                v
                for v in versions
                if v.strategy == STRATEGY_STRUCTURED and v.status != "abandoned"
            ]
            if not structured:
                raise HTTPException(
                    status_code=422,
                    detail=f"{doc_id}: no structured version to revert to",
                )
            target = structured[-1].version
        try:
            live = revert_to(db, doc_id, target)
        except LifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return VersionActionResponse(
            doc_id=doc_id,
            version=live.version,
            status=live.status,
            strategy=live.strategy,
            detail="reverted; the semantic version is superseded but still stored",
            active_version=live.version,
            active_strategy=live.strategy,
        )


    @router.get("/documents/{doc_id}/pdf")
    def get_document_pdf(doc_id: str):
        """Stream the manufacturer PDF for the PDF.js review surface (ADR-0049)."""
        from fastapi.responses import FileResponse

        pdf = _pdf_path(doc_id)
        return FileResponse(
            path=str(pdf),
            media_type="application/pdf",
            filename=pdf.name,
        )

    # --- representations assist (ADR-0053) ---------------------------------

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/assist/sessions",
        response_model=AssistSessionOut,
    )
    def create_assist_session(
        doc_id: str,
        version: int,
        body: AssistSessionCreateRequest | None = None,
        db: Database = Depends(get_db),
    ) -> AssistSessionOut:
        """Start an in-memory specialist chat for rep curation."""
        found = _editable(db, doc_id, version)
        request = body or AssistSessionCreateRequest()
        if request.unit_key:
            _unit(db, found.id, request.unit_key)
        session = sessions.create(
            doc_id=doc_id,
            version=found.version,
            unit_key=request.unit_key,
        )
        return AssistSessionOut(
            session_id=session.session_id,
            doc_id=session.doc_id,
            version=session.version,
            unit_key=session.unit_key,
        )

    @router.post(
        "/documents/{doc_id}/semantic/versions/{version}/assist/sessions/{session_id}/message",
        response_model=AssistMessageResponse,
    )
    def assist_message(
        doc_id: str,
        version: int,
        session_id: str,
        body: AssistMessageRequest,
        db: Database = Depends(get_db),
    ) -> AssistMessageResponse:
        """Suggest overview/facts/questions edits; does not write the corpus."""
        from repair_assistant.observability.langfuse_tracing import (
            observation,
            update_span,
        )
        from repair_assistant.semantic import assist as assist_mod

        found = _editable(db, doc_id, version)
        try:
            session = sessions.get(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=410,
                detail="assist session expired or unknown",
            ) from exc
        if session.doc_id != doc_id or session.version != found.version:
            raise HTTPException(
                status_code=409,
                detail="assist session does not match this document version",
            )
        unit = _unit(db, found.id, body.unit_key)
        draft = None
        if body.draft is not None:
            draft = {
                "overview": body.draft.overview,
                "facts": list(body.draft.facts),
                "questions": list(body.draft.questions),
            }
        client = _requires_llm(
            assist_client or (lambda: assist_mod.build_assist_client()),
            "corpus assist",
        )
        document = _manifest_document(doc_id)
        doc_ctx = assist_mod.DocumentContext(
            doc_id=doc_id,
            title=(document.title if document else "") or "",
            doc_type=(document.doc_type if document else "") or "",
            publication_number=(document.publication_number if document else "")
            or "",
            revision=(document.revision if document else "") or "",
        )
        pdf: Path | None = None
        looks_scanned = False
        try:
            pdf = _pdf_path(doc_id)
            from repair_assistant.corpus.identity import inspect

            looks_scanned = bool(inspect(pdf).looks_scanned)
        except Exception:  # noqa: BLE001 — text-only fallback
            pdf = None
            looks_scanned = False

        def _raster(doc: str, page: int) -> Path | None:
            from repair_assistant.qa.page_images import ensure_page_raster

            return ensure_page_raster(manifest(), doc, page)

        attachments = assist_mod.prepare_unit_attachments(
            pdf_path=pdf,
            unit=unit,
            doc_id=doc_id,
            looks_scanned=looks_scanned,
            raster_loader=_raster if looks_scanned else None,
        )
        with observation(
            "corpus_assist",
            input={
                "doc_id": doc_id,
                "version": found.version,
                "unit_key": unit.unit_key,
                "message": body.message,
                "attachment_modality": attachments.modality,
                "pages": unit.page_label,
            },
            metadata={
                "assist_session_id": session_id,
                "prompt_version": assist_mod.assist_prompt_version(),
                "attachment_modality": attachments.modality,
            },
            session_id=session_id,
        ) as span:
            try:
                suggestion = assist_mod.run_assist_turn(
                    session=session,
                    unit=unit,
                    message=body.message,
                    draft=draft,
                    llm=client,
                    document=doc_ctx,
                    attachments=attachments,
                )
            except assist_mod.AssistError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            update_span(
                span,
                output={
                    "rationale": suggestion.rationale,
                    "overview": suggestion.overview,
                    "facts": suggestion.facts,
                    "questions": suggestion.questions,
                    "attachment_modality": attachments.modality,
                },
            )
        return AssistMessageResponse(
            session_id=session_id,
            unit_key=unit.unit_key,
            suggestion=AssistSuggestionOut(**suggestion.as_dict()),
            prompt_version=assist_mod.assist_prompt_version(),
        )

    @router.delete(
        "/documents/{doc_id}/semantic/versions/{version}/assist/sessions/{session_id}",
    )
    def delete_assist_session(
        doc_id: str,
        version: int,
        session_id: str,
    ) -> dict[str, bool]:
        try:
            session = sessions.get(session_id)
        except KeyError:
            return {"deleted": False}
        if session.doc_id != doc_id or session.version != version:
            raise HTTPException(
                status_code=409,
                detail="assist session does not match this document version",
            )
        return {"deleted": sessions.delete(session_id)}

    return router


__all__ = ["build_corpus_router"]
