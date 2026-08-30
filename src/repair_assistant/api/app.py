"""FastAPI application factory and routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Generator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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
from repair_assistant.diagnostic.session import (
    DEFAULT_SESSION_MAX_TURNS,
    SessionTurnLimitError,
)
from repair_assistant.ingest.embeddings import (
    EmbeddingModelMismatch,
    assert_embedding_model,
    get_shared_embedder,
    shared_embedder_loaded,
)
from repair_assistant.ingest.env import database_url, load_dotenv_files
from repair_assistant.ingest.store import Database
from repair_assistant.observability.scope_detectors import worker_count_warning
from repair_assistant.qa.generate import (
    LLMError,
    LLMTimeoutError,
    ask_stream,
    complete_ask,
    prepare_ask,
)
from repair_assistant.retrieval.search import search
from repair_assistant.safety.audience_claim import record_audience_claim
from repair_assistant.safety.classifier import runtime_classifier
from repair_assistant.safety.models import Audience

_log = logging.getLogger("repair_assistant.api")


def _llm_timeout_http(exc: BaseException) -> HTTPException:
    return HTTPException(status_code=504, detail=_client_detail(exc, "LLM request timed out"))


def _client_detail(exc: BaseException, fallback: str) -> str:
    """Client-safe message for an exception, always logging the real one.

    Errors carrying a `client_message` (the LLM taxonomy) report that instead of
    provider text, which can include request ids, org ids, and key prefixes. The
    project's own `RuntimeError` messages are deliberately still surfaced: for a
    self-hosted operator "OPENAI_API_KEY is required" is the useful answer, and it
    is our text, not a third party's (review R36).
    """
    _log.warning("%s: %s", type(exc).__name__, exc)
    return getattr(exc, "client_message", None) or str(exc) or fallback


def _llm_error_http(exc: BaseException) -> HTTPException:
    status = getattr(exc, "status_code", None) or 503
    return HTTPException(
        status_code=status,
        detail=_client_detail(exc, "The language model is unavailable."),
    )


def _stream_error_event(exc: BaseException, *, generic: bool = False) -> dict[str, str]:
    """SSE error payload. `generic` withholds detail for unanticipated errors."""
    if generic:
        _log.exception("Unhandled error on a streaming route", exc_info=exc)
        return {"type": "error", "detail": "The request could not be completed."}
    return {"type": "error", "detail": _client_detail(exc, "The request failed.")}

def _citation_out(cite) -> CitationOut:
    return CitationOut(
        index=cite.index,
        doc_id=cite.doc_id,
        chunk_id=cite.chunk_id,
        label=cite.label,
        page=cite.page,
    )


_manifest_cache = None
_manifest_stamp: tuple | None = None


def _manifest_dir() -> Path:
    return manifest_mod.repo_root() / "corpus" / "manifest"


def _read_manifest_stamp() -> tuple:
    """Fingerprint of every YAML file so edits invalidate the cache (review R40)."""
    root = _manifest_dir()
    if not root.is_dir():
        return ()
    return tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.glob("*.yaml"))
    )


def invalidate_manifest_cache() -> None:
    global _manifest_cache, _manifest_stamp
    _manifest_cache = None
    _manifest_stamp = None


def _manifest():
    """Load the corpus manifest, re-reading when files change or after reload."""
    global _manifest_cache, _manifest_stamp
    stamp = _read_manifest_stamp()
    if _manifest_cache is None or stamp != _manifest_stamp:
        _manifest_cache = manifest_mod.load()
        _manifest_stamp = stamp
    return _manifest_cache


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


def _pull_stream_event(gen: Iterator[Any]) -> Any | None:
    """Return the next sync-generator event, or None when exhausted.

    Do not pass ``next`` directly to ``asyncio.to_thread``: StopIteration in the
    worker thread becomes RuntimeError when the Future completes.
    """
    try:
        return next(gen)
    except StopIteration:
        return None


def _generation_begun(event: dict[str, Any]) -> bool:
    """True once retrieval is finished and the LLM (or its tokens) may start."""
    if event.get("type") == "status" and event.get("phase") == "generating":
        return True
    return event.get("type") == "token"


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
        max_turns=_env_int("REPAIR_SESSION_MAX_TURNS", DEFAULT_SESSION_MAX_TURNS),
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
        host = os.environ.get("REPAIR_API_HOST", "127.0.0.1")
        key = os.environ.get("REPAIR_API_KEY", "").strip()
        if not key and host not in {"127.0.0.1", "localhost", "::1"}:
            _log.warning(
                "api_bind host=%s auth=unset — LAN exposure is opt-in; "
                "set REPAIR_API_KEY or bind 127.0.0.1 (review R5 / ADR-0025)",
                host,
            )
        workers_warning = worker_count_warning()
        if workers_warning:
            _log.warning("%s", workers_warning)
        if pool is not None:
            try:
                with pool.connection() as db:
                    assert_embedding_model(db)
            except EmbeddingModelMismatch:
                raise
            except Exception as exc:  # noqa: BLE001 — no DB yet is not a model bug
                _log.warning("embedding_model_guard skipped detail=%s", exc)
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

    def _db_factory():
        factory = db_connection if db_factory is None else db_factory
        return factory

    def _db_error_http(exc: BaseException) -> HTTPException:
        return HTTPException(status_code=503, detail=_client_detail(exc, "Unavailable"))

    async def _sse_releasing(
        request: Request,
        start_gen,
        *,
        mutate_event=None,
    ) -> AsyncIterator[str]:
        """Yield SSE lines; return the pool connection once generation begins (R35)."""
        gen = None
        factory = _db_factory()
        try:
            with factory() as db:
                gen = start_gen(db)
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.to_thread(_pull_stream_event, gen)
                    except (LLMTimeoutError, RuntimeError) as exc:
                        yield f"data: {json.dumps(_stream_error_event(exc), ensure_ascii=False)}\n\n"
                        return
                    except Exception as exc:  # noqa: BLE001 — logged, not echoed
                        yield f"data: {json.dumps(_stream_error_event(exc, generic=True), ensure_ascii=False)}\n\n"
                        return
                    if event is None:
                        return
                    if mutate_event is not None:
                        mutate_event(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "done":
                        return
                    if _generation_begun(event):
                        break
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.to_thread(_pull_stream_event, gen)
                except (LLMTimeoutError, RuntimeError) as exc:
                    yield f"data: {json.dumps(_stream_error_event(exc), ensure_ascii=False)}\n\n"
                    return
                except Exception as exc:  # noqa: BLE001 — logged, not echoed
                    yield f"data: {json.dumps(_stream_error_event(exc, generic=True), ensure_ascii=False)}\n\n"
                    return
                if event is None:
                    return
                if mutate_event is not None:
                    mutate_event(event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    return
        except RuntimeError as exc:
            yield f"data: {json.dumps(_stream_error_event(exc), ensure_ascii=False)}\n\n"
        finally:
            close = getattr(gen, "close", None)
            if callable(close):
                close()

    @app.post("/v1/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
    def ask_route(body: AskRequest) -> AskResponse:
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None
        record_audience_claim(
            body.audience,
            attested=body.technician_attested,
            source="api_ask",
        )
        try:
            with _db_factory()() as db:
                prep = prepare_ask(
                    db,
                    _manifest(),
                    body.question,
                    appliance=appliance,
                    audience=Audience(body.audience),
                    retrieval_limit=body.limit,
                    overfetch=body.overfetch,
                    classifier=runtime_classifier(),
                )
            result = complete_ask(prep)
        except LLMTimeoutError as exc:
            raise _llm_timeout_http(exc) from exc
        except LLMError as exc:
            raise _llm_error_http(exc) from exc
        except RuntimeError as exc:
            raise _db_error_http(exc) from exc
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
    async def ask_stream_route(
        request: Request,
        body: AskRequest,
    ) -> StreamingResponse:
        """SSE stream: status / token / done events for grounded ask()."""
        appliance = Appliance(model=body.model, serial=body.serial) if body.model else None

        def start_gen(db: Database):
            return ask_stream(
                db,
                _manifest(),
                body.question,
                appliance=appliance,
                audience=Audience(body.audience),
                retrieval_limit=body.limit,
                overfetch=body.overfetch,
                technician_attested=body.technician_attested,
            )

        return StreamingResponse(
            _sse_releasing(request, start_gen),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/diagnose", response_model=DiagnoseResponse, dependencies=[Depends(require_api_key)])
    def diagnose_route(body: DiagnoseRequest) -> DiagnoseResponse:
        appliance = Appliance(model=body.model, serial=body.serial)
        try:
            sid, session = store.get_or_create(
                body.session_id,
                manifest=_manifest(),
                appliance=appliance,
                audience=Audience(body.audience),
                retrieval_limit=body.limit,
                overfetch=body.overfetch,
                technician_attested=body.technician_attested,
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
            turn = session.send_releasing(_db_factory(), body.message)
        except SessionTurnLimitError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.client_message,
            ) from exc
        except LLMTimeoutError as exc:
            raise _llm_timeout_http(exc) from exc
        except LLMError as exc:
            raise _llm_error_http(exc) from exc
        except RuntimeError as exc:
            raise _db_error_http(exc) from exc
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
            diagnostic=turn.diagnostic if isinstance(turn.diagnostic, dict) else None,
        )

    @app.post("/v1/diagnose/stream", dependencies=[Depends(require_api_key)])
    async def diagnose_stream_route(
        request: Request,
        body: DiagnoseRequest,
    ) -> StreamingResponse:
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
                technician_attested=body.technician_attested,
            )
        except KeyError:
            raise HTTPException(
                status_code=410,
                detail=(
                    "diagnostic session expired or unknown after API restart; "
                    "start a new chat"
                ),
            ) from None
        if session.turn_count >= session.max_turns:
            raise HTTPException(
                status_code=SessionTurnLimitError.status_code,
                detail=SessionTurnLimitError.client_message,
            )

        def start_gen(db: Database):
            return session.send_stream(db, body.message)

        def attach_session(event: dict[str, Any]) -> None:
            if event.get("type") == "done":
                event["session_id"] = sid

        return StreamingResponse(
            _sse_releasing(request, start_gen, mutate_event=attach_session),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/reload-manifest", dependencies=[Depends(require_api_key)])
    def reload_manifest() -> dict[str, Any]:
        """Drop the in-process manifest cache and reload from disk (review R40)."""
        invalidate_manifest_cache()
        loaded = _manifest()
        return {"reloaded": True, "documents": len(loaded.documents)}

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
