"""FastAPI application factory and routes."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException

from repair_assistant.api.schemas import (
    AskRequest,
    AskResponse,
    CitationOut,
    DiagnoseRequest,
    DiagnoseResponse,
    HealthResponse,
    ReadyResponse,
    SearchHitOut,
    SearchRequest,
    SearchResponse,
)
from repair_assistant.api.sessions import SessionStore
from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.ingest.env import database_url, load_dotenv_files
from repair_assistant.ingest.store import Database
from repair_assistant.qa.generate import ask
from repair_assistant.retrieval.search import search
from repair_assistant.safety.models import Audience


def _citation_out(cite) -> CitationOut:
    return CitationOut(
        index=cite.index,
        doc_id=cite.doc_id,
        chunk_id=cite.chunk_id,
        label=cite.label,
        page=cite.page,
    )


@lru_cache
def _manifest():
    return manifest_mod.load()


def _session_store() -> SessionStore:
    return SessionStore()


_store = _session_store()


def create_app(
    *,
    session_store: SessionStore | None = None,
    db_factory=None,
) -> FastAPI:
    load_dotenv_files()
    store = session_store or _store
    app = FastAPI(
        title="AI Repair Assistant",
        description="Grounded repair Q&A over manufacturer documentation.",
        version="0.1.0",
    )

    def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
        expected = os.environ.get("REPAIR_API_KEY", "").strip()
        if expected and x_api_key != expected:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    @contextmanager
    def db_connection() -> Generator[Database, None, None]:
        with Database(database_url()) as db:
            yield db

    def get_db() -> Generator[Database, None, None]:
        try:
            factory = db_connection if db_factory is None else db_factory
            with factory() as db:
                yield db
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    def ready(db: Database = Depends(get_db)) -> ReadyResponse:
        row = db.fetchone("SELECT 1")
        if row is None:
            raise HTTPException(status_code=503, detail="database not ready")
        return ReadyResponse(status="ready", database="ok")

    @app.post("/v1/search", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
    def search_route(body: SearchRequest, db: Database = Depends(get_db)) -> SearchResponse:
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None
        result = search(
            db,
            _manifest(),
            body.query,
            appliance=appliance,
            limit=body.limit,
            overfetch=body.overfetch,
        )
        hits = [
            SearchHitOut(
                doc_id=h.doc_id,
                chunk_id=h.chunk_id,
                text=h.text,
                page=h.page,
                score=h.score,
                publication_number=h.publication_number,
                error_codes=h.error_codes,
            )
            for h in result.hits
        ]
        return SearchResponse(
            query=result.query,
            hits=hits,
            fetched=result.fetched,
            filtered_out=result.filtered_out,
        )

    @app.post("/v1/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
    def ask_route(body: AskRequest, db: Database = Depends(get_db)) -> AskResponse:
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None
        try:
            result = ask(
                db,
                _manifest(),
                body.question,
                appliance=appliance,
                audience=Audience(body.audience),
                retrieval_limit=body.limit,
                overfetch=body.overfetch,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return AskResponse(
            question=result.question,
            answer=result.answer,
            abstained=result.abstained,
            abstain_reason=result.abstain_reason,
            citations=[_citation_out(c) for c in result.citations],
            retrieval_count=result.retrieval_count,
            safety_action=result.safety_action,
            safety_notice=result.safety_notice,
            escalated=result.escalated,
        )

    @app.post("/v1/diagnose", response_model=DiagnoseResponse, dependencies=[Depends(require_api_key)])
    def diagnose_route(body: DiagnoseRequest, db: Database = Depends(get_db)) -> DiagnoseResponse:
        appliance = Appliance(model=body.model, serial=body.serial)
        sid, session = store.get_or_create(
            body.session_id,
            manifest=_manifest(),
            appliance=appliance,
            audience=Audience(body.audience),
            retrieval_limit=body.limit,
            overfetch=body.overfetch,
        )
        try:
            turn = session.send(db, body.message)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return DiagnoseResponse(
            session_id=sid,
            turn=turn.turn,
            assistant_message=turn.assistant_message,
            abstained=turn.abstained,
            abstain_reason=turn.abstain_reason,
            citations=[_citation_out(c) for c in turn.citations],
            retrieval_count=turn.retrieval_count,
            safety_action=turn.safety_action,
            safety_notice=turn.safety_notice,
            escalated=turn.escalated,
        )

    @app.delete("/v1/diagnose/{session_id}", dependencies=[Depends(require_api_key)])
    def diagnose_delete(session_id: str) -> dict[str, bool]:
        return {"deleted": store.delete(session_id)}

    app.state.session_store = store
    return app


app = create_app()
