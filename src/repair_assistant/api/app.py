"""FastAPI application factory and routes."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json

from repair_assistant.api.db_pool import (
    DEFAULT_POOL_SIZE,
    DEFAULT_POOL_TIMEOUT_SECONDS,
    DatabasePool,
)
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
from repair_assistant.api.sessions import (
    DEFAULT_SESSION_MAX,
    DEFAULT_SESSION_TTL_SECONDS,
    SessionStore,
)
from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.support import (
    ABSTAIN_UNSUPPORTED_MODEL,
    corpus_supports_appliance,
    unsupported_appliance_message,
)
from repair_assistant.ingest.embeddings import get_shared_embedder, shared_embedder_loaded
from repair_assistant.ingest.env import database_url, load_dotenv_files
from repair_assistant.ingest.store import Database
from repair_assistant.qa.generate import LLMTimeoutError, ask, ask_stream
from repair_assistant.retrieval.search import search
from repair_assistant.safety.models import Audience

_log = logging.getLogger("repair_assistant.api")


def _llm_timeout_http(exc: BaseException) -> HTTPException:
    return HTTPException(
        status_code=504,
        detail=str(exc) or "LLM request timed out",
    )

def _citation_out(cite) -> CitationOut:
    return CitationOut(
        index=cite.index,
        doc_id=cite.doc_id,
        chunk_id=cite.chunk_id,
        label=cite.label,
        page=cite.page,
    )


def _manifest():
    return manifest_mod.load()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def create_app(
    *,
    session_store: SessionStore | None = None,
    db_factory=None,
    warmup_embedder: bool | None = None,
) -> FastAPI:
    load_dotenv_files()
    store = session_store or SessionStore(
        ttl_seconds=_env_int("REPAIR_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS),
        max_sessions=_env_int("REPAIR_SESSION_MAX", DEFAULT_SESSION_MAX),
    )
    pool: DatabasePool | None = None
    if db_factory is None:
        try:
            pool = DatabasePool(
                database_url(),
                size=_env_int("REPAIR_DB_POOL_SIZE", DEFAULT_POOL_SIZE),
                timeout_seconds=_env_float(
                    "REPAIR_DB_POOL_TIMEOUT_SECONDS",
                    DEFAULT_POOL_TIMEOUT_SECONDS,
                ),
            )
        except RuntimeError:
            pool = None

    skip_warmup = os.environ.get("REPAIR_SKIP_EMBEDDER_WARMUP", "").strip() in {
        "1",
        "true",
        "yes",
    }
    do_warmup = (not skip_warmup) if warmup_embedder is None else warmup_embedder

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if do_warmup:
            try:
                get_shared_embedder()
                _log.info("embedder_warmup status=ok")
            except Exception as exc:
                _log.warning("embedder_warmup status=failed detail=%s", exc)
        yield
        if pool is not None:
            pool.close()

    app = FastAPI(
        title="AI Repair Assistant",
        description="Grounded repair Q&A over manufacturer documentation.",
        version="0.1.0",
        lifespan=lifespan,
    )

    def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
        expected = os.environ.get("REPAIR_API_KEY", "").strip()
        if expected and x_api_key != expected:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    @contextmanager
    def db_connection() -> Generator[Database, None, None]:
        if pool is not None:
            with pool.connection() as db:
                yield db
        else:
            with Database(database_url()) as db:
                yield db

    def get_db() -> Generator[Database, None, None]:
        try:
            factory = db_connection if db_factory is None else db_factory
            with factory() as db:
                yield db
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.middleware("http")
    async def request_timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        path = request.url.path
        if path.startswith("/v1/") or path in {"/ready", "/health"}:
            _log.info(
                "http_request method=%s path=%s status=%s duration_ms=%s",
                request.method,
                path,
                response.status_code,
                elapsed_ms,
            )
        return response

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    def ready(db: Database = Depends(get_db)) -> ReadyResponse:
        row = db.fetchone("SELECT 1")
        if row is None:
            raise HTTPException(status_code=503, detail="database not ready")
        return ReadyResponse(
            status="ready",
            database="ok",
            embedder="loaded" if shared_embedder_loaded() else "cold",
            sessions=store.count(),
        )

    @app.post("/v1/search", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
    def search_route(body: SearchRequest, db: Database = Depends(get_db)) -> SearchResponse:
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None
        if appliance is not None and not corpus_supports_appliance(_manifest(), appliance).supported:
            return SearchResponse(
                query=body.query,
                hits=[],
                fetched=0,
                filtered_out=0,
                notice=unsupported_appliance_message(appliance),
                abstain_code=ABSTAIN_UNSUPPORTED_MODEL,
            )
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
        except LLMTimeoutError as exc:
            raise _llm_timeout_http(exc) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return AskResponse(
            question=result.question,
            answer=result.answer,
            abstained=result.abstained,
            abstain_reason=result.abstain_reason,
            abstain_code=result.abstain_code,
            citations=[_citation_out(c) for c in result.citations],
            retrieval_count=result.retrieval_count,
            safety_action=result.safety_action,
            safety_notice=result.safety_notice,
            escalated=result.escalated,
        )

    @app.post("/v1/ask/stream", dependencies=[Depends(require_api_key)])
    def ask_stream_route(body: AskRequest, db: Database = Depends(get_db)) -> StreamingResponse:
        """SSE stream: status / token / done events for grounded ask()."""
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None

        def event_iter():
            try:
                for event in ask_stream(
                    db,
                    _manifest(),
                    body.question,
                    appliance=appliance,
                    audience=Audience(body.audience),
                    retrieval_limit=body.limit,
                    overfetch=body.overfetch,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except LLMTimeoutError as exc:
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            except RuntimeError as exc:
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001 — surface to client
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_iter(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/diagnose", response_model=DiagnoseResponse, dependencies=[Depends(require_api_key)])
    def diagnose_route(body: DiagnoseRequest, db: Database = Depends(get_db)) -> DiagnoseResponse:
        appliance = Appliance(model=body.model, serial=body.serial)
        try:
            sid, session = store.get_or_create(
                body.session_id,
                manifest=_manifest(),
                appliance=appliance,
                audience=Audience(body.audience),
                retrieval_limit=body.limit,
                overfetch=body.overfetch,
            )
        except KeyError:
            raise HTTPException(
                status_code=410,
                detail=(
                    "diagnostic session expired or unknown after API restart; "
                    "start a new chat"
                ),
            ) from None
        try:
            turn = session.send(db, body.message)
        except LLMTimeoutError as exc:
            raise _llm_timeout_http(exc) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return DiagnoseResponse(
            session_id=sid,
            turn=turn.turn,
            assistant_message=turn.assistant_message,
            abstained=turn.abstained,
            abstain_reason=turn.abstain_reason,
            abstain_code=turn.abstain_code,
            citations=[_citation_out(c) for c in turn.citations],
            retrieval_count=turn.retrieval_count,
            safety_action=turn.safety_action,
            safety_notice=turn.safety_notice,
            escalated=turn.escalated,
        )

    @app.post("/v1/diagnose/stream", dependencies=[Depends(require_api_key)])
    def diagnose_stream_route(body: DiagnoseRequest, db: Database = Depends(get_db)) -> StreamingResponse:
        """SSE stream: status / token / done events for multi-turn diagnose()."""
        appliance = Appliance(model=body.model, serial=body.serial)
        try:
            sid, session = store.get_or_create(
                body.session_id,
                manifest=_manifest(),
                appliance=appliance,
                audience=Audience(body.audience),
                retrieval_limit=body.limit,
                overfetch=body.overfetch,
            )
        except KeyError:
            raise HTTPException(
                status_code=410,
                detail=(
                    "diagnostic session expired or unknown after API restart; "
                    "start a new chat"
                ),
            ) from None

        def event_iter():
            try:
                for event in session.send_stream(db, body.message):
                    if event.get("type") == "done":
                        event["session_id"] = sid
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except LLMTimeoutError as exc:
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            except RuntimeError as exc:
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001 — surface to client
                err = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_iter(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/v1/diagnose/{session_id}", dependencies=[Depends(require_api_key)])
    def diagnose_delete(session_id: str) -> dict[str, bool]:
        return {"deleted": store.delete(session_id)}

    app.state.session_store = store

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/ui/static", StaticFiles(directory=static_dir), name="ui-static")

        @app.get("/ui")
        def ui_page() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/")
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui")

    return app


app = create_app()
