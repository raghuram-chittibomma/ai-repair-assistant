"""HTTP API tests (mocked DB and backends)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from repair_assistant.api.app import create_app
from repair_assistant.api.sessions import SessionStore
from repair_assistant.qa.context import AnswerResult, Citation
from repair_assistant.retrieval.search import Hit, SearchResult


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.fetchone.return_value = (1,)
    return db


@pytest.fixture
def client(mock_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REPAIR_SKIP_EMBEDDER_WARMUP", "1")

    @contextmanager
    def factory():
        yield mock_db

    app = create_app(
        session_store=SessionStore(ttl_seconds=3600, max_sessions=8),
        db_factory=factory,
        warmup_embedder=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health_no_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_checks_database(client: TestClient, mock_db: MagicMock) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["embedder"] in {"cold", "loaded"}
    assert "sessions" in body
    mock_db.fetchone.assert_called_once()


def test_api_key_required_when_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPAIR_API_KEY", "secret")
    response = client.post("/v1/ask", json={"question": "hi"})
    assert response.status_code == 401
    with (
        patch("repair_assistant.api.app.prepare_ask") as mock_prep,
        patch("repair_assistant.api.app.complete_ask") as mock_complete,
    ):
        mock_complete.return_value = AnswerResult(question="hi", answer="ok", abstained=False)
        response = client.post(
            "/v1/ask",
            json={"question": "hi"},
            headers={"X-API-Key": "secret"},
        )
    assert response.status_code == 200
    mock_prep.assert_called_once()


@patch("repair_assistant.api.app.complete_ask")
@patch("repair_assistant.api.app.prepare_ask")
def test_ask_llm_timeout_returns_504(
    mock_prep: MagicMock, mock_complete: MagicMock, client: TestClient
) -> None:
    from repair_assistant.qa.generate import LLMTimeoutError

    mock_complete.side_effect = LLMTimeoutError("OpenAI request timed out after 120s")
    response = client.post("/v1/ask", json={"question": "What is F5E2?"})
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


def test_ask_rejects_oversized_question(client: TestClient) -> None:
    response = client.post("/v1/ask", json={"question": "x" * 4001})
    assert response.status_code == 422


@patch("repair_assistant.api.app.complete_ask")
@patch("repair_assistant.api.app.prepare_ask")
def test_ask_route(mock_prep: MagicMock, mock_complete: MagicMock, client: TestClient) -> None:
    mock_complete.return_value = AnswerResult(
        question="What is F5E2?",
        answer="Door lock failure [1].",
        abstained=False,
        citations=[
            Citation(
                index=1,
                doc_id="tech-sheet-w11320651",
                chunk_id="p1",
                label="W11320651 p.1",
                page=1,
                excerpt="F5E2",
            )
        ],
        retrieval_count=3,
    )
    response = client.post("/v1/ask", json={"question": "What is F5E2?", "model": "WFW5620HW0"})
    assert response.status_code == 200
    body = response.json()
    assert "F5E2" in body["question"]
    assert body["citations"][0]["doc_id"] == "tech-sheet-w11320651"


def test_ask_releases_db_before_generation(mock_db: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review R35: the pool connection must not be held across complete_ask."""
    held = {"n": 0}

    @contextmanager
    def factory():
        held["n"] += 1
        yield mock_db
        held["n"] -= 1

    monkeypatch.setenv("REPAIR_SKIP_EMBEDDER_WARMUP", "1")
    app = create_app(
        session_store=SessionStore(ttl_seconds=3600, max_sessions=8),
        db_factory=factory,
        warmup_embedder=False,
    )

    def fake_prepare(*_args, **_kwargs):
        assert held["n"] == 1
        return MagicMock()

    def fake_complete(_prep, **_kwargs):
        assert held["n"] == 0
        return AnswerResult(question="What is F5E2?", answer="ok", abstained=False)

    with (
        TestClient(app) as test_client,
        patch("repair_assistant.api.app.prepare_ask", side_effect=fake_prepare),
        patch("repair_assistant.api.app.complete_ask", side_effect=fake_complete),
    ):
        response = test_client.post("/v1/ask", json={"question": "What is F5E2?"})
    assert response.status_code == 200


@patch("repair_assistant.api.app.search")
def test_search_route(mock_search: MagicMock, client: TestClient) -> None:
    mock_search.return_value = SearchResult(
        query="F5E2",
        hits=[
            Hit(
                doc_id="tech-sheet-w11320651",
                chunk_id="p1",
                text="F5E2 door lock",
                page=1,
                kind="table_row",
                error_codes=["F5E2"],
                publication_number="W11320651",
                revision="A",
                score=0.9,
            )
        ],
        fetched=1,
        filtered_out=0,
    )
    response = client.post("/v1/search", json={"query": "F5E2", "model": "WFW5620HW0"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["hits"]) == 1
    assert body["hits"][0]["doc_id"] == "tech-sheet-w11320651"


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_route_returns_session_id(mock_session_cls: MagicMock, client: TestClient) -> None:
    instance = MagicMock()
    turn = MagicMock(
        turn=1,
        assistant_message="Check TEST #4 [1].",
        abstained=False,
        abstain_reason="",
        abstain_code="",
        citations=[],
        retrieval_count=4,
        safety_action="allow",
        safety_notice="",
        escalated=False,
    )
    instance.send_releasing.return_value = turn
    instance.turn_count = 0
    instance.max_turns = 24
    mock_session_cls.return_value = instance

    response = client.post(
        "/v1/diagnose",
        json={"message": "F5E2", "model": "WFW5620HW0"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["turn"] == 1


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_unknown_session_returns_410(
    mock_session_cls: MagicMock, client: TestClient
) -> None:
    response = client.post(
        "/v1/diagnose",
        json={
            "message": "still broken",
            "model": "WFW5620HW0",
            "session_id": "does-not-exist",
        },
    )
    assert response.status_code == 410
    assert "expired" in response.json()["detail"].lower()
    mock_session_cls.assert_not_called()


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_turn_limit_returns_400(
    mock_session_cls: MagicMock, client: TestClient
) -> None:
    from repair_assistant.diagnostic.session import SessionTurnLimitError

    instance = MagicMock()
    instance.send_releasing.side_effect = SessionTurnLimitError(SessionTurnLimitError.client_message)
    instance.turn_count = 24
    instance.max_turns = 24
    mock_session_cls.return_value = instance
    response = client.post(
        "/v1/diagnose",
        json={"message": "still stuck", "model": "WFW5620HW0"},
    )
    assert response.status_code == 400
    assert "turn limit" in response.json()["detail"].lower()


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_stream_turn_limit_returns_400(
    mock_session_cls: MagicMock, client: TestClient
) -> None:
    instance = MagicMock()
    instance.turn_count = 24
    instance.max_turns = 24
    mock_session_cls.return_value = instance
    response = client.post(
        "/v1/diagnose/stream",
        json={"message": "still stuck", "model": "WFW5620HW0"},
    )
    assert response.status_code == 400
    assert "turn limit" in response.json()["detail"].lower()
    instance.send_stream.assert_not_called()


@patch("repair_assistant.api.app.ask_stream")
def test_ask_stream_route_sse(mock_stream: MagicMock, client: TestClient) -> None:
    mock_stream.return_value = iter(
        [
            {"type": "status", "phase": "retrieving"},
            {"type": "token", "text": "Hi"},
            {
                "type": "done",
                "question": "x",
                "answer": "Hi",
                "abstained": False,
                "abstain_reason": "",
                "citations": [],
                "retrieval_count": 1,
                "safety_action": "allow",
                "safety_notice": "",
                "escalated": False,
            },
        ]
    )
    response = client.post("/v1/ask/stream", json={"question": "What is F5E2?"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "data: " in response.text
    assert '"type": "token"' in response.text or '"type":"token"' in response.text
    assert '"type": "error"' not in response.text
    assert "StopIteration" not in response.text


@patch("repair_assistant.api.app.ask_stream")
def test_ask_stream_route_exhaustion_no_stopiteration_error(
    mock_stream: MagicMock, client: TestClient
) -> None:
    """After the done event, generator exhaustion must not surface as SSE error."""
    mock_stream.return_value = iter([{"type": "done", "answer": "ok", "abstained": False}])
    response = client.post("/v1/ask/stream", json={"question": "test"})
    assert response.status_code == 200
    assert '"type": "error"' not in response.text
    assert "StopIteration" not in response.text


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_stream_route_sse(mock_session_cls: MagicMock, client: TestClient) -> None:
    instance = MagicMock()
    instance.turn_count = 0
    instance.max_turns = 24
    instance.send_stream.return_value = iter(
        [
            {"type": "status", "phase": "retrieving"},
            {"type": "token", "text": "Check"},
            {
                "type": "done",
                "assistant_message": "Check wiring [1].",
                "abstained": False,
                "abstain_reason": "",
                "citations": [],
                "retrieval_count": 2,
                "safety_action": "allow",
                "safety_notice": "",
                "escalated": False,
                "turn": 1,
            },
        ]
    )
    mock_session_cls.return_value = instance

    response = client.post(
        "/v1/diagnose/stream",
        json={"message": "F5E2", "model": "WFW5620HW0"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "session_id" in response.text
    assert '"type": "token"' in response.text or '"type":"token"' in response.text
    assert '"type": "error"' not in response.text
    assert "StopIteration" not in response.text


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_stream_route_exhaustion_no_stopiteration_error(
    mock_session_cls: MagicMock, client: TestClient
) -> None:
    instance = MagicMock()
    instance.turn_count = 0
    instance.max_turns = 24
    instance.send_stream.return_value = iter(
        [{"type": "done", "assistant_message": "Done.", "abstained": False, "turn": 1}]
    )
    mock_session_cls.return_value = instance
    response = client.post(
        "/v1/diagnose/stream",
        json={"message": "noise", "model": "WFW5620HW0"},
    )
    assert response.status_code == 200
    assert '"type": "error"' not in response.text
    assert "StopIteration" not in response.text


@patch("repair_assistant.api.sessions.DiagnosticSession")
def test_diagnose_stream_unknown_session_returns_410(
    mock_session_cls: MagicMock, client: TestClient
) -> None:
    response = client.post(
        "/v1/diagnose/stream",
        json={
            "message": "still broken",
            "model": "WFW5620HW0",
            "session_id": "does-not-exist",
        },
    )
    assert response.status_code == 410
    mock_session_cls.assert_not_called()


def test_manifest_cache_reuses_until_invalidated() -> None:
    import importlib

    app_mod = importlib.import_module("repair_assistant.api.app")
    app_mod.invalidate_manifest_cache()
    with patch.object(app_mod.manifest_mod, "load", wraps=app_mod.manifest_mod.load) as load:
        first = app_mod._manifest()
        second = app_mod._manifest()
        assert first is second
        assert load.call_count == 1
        app_mod.invalidate_manifest_cache()
        third = app_mod._manifest()
        assert load.call_count == 2
        assert third is not first


def test_manifest_cache_reloads_when_stamp_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    app_mod = importlib.import_module("repair_assistant.api.app")
    stamps = iter([(("a",),), (("b",),)])
    monkeypatch.setattr(app_mod, "_read_manifest_stamp", lambda: next(stamps))
    app_mod.invalidate_manifest_cache()
    with patch.object(app_mod.manifest_mod, "load", wraps=app_mod.manifest_mod.load) as load:
        app_mod._manifest()
        app_mod._manifest()
        assert load.call_count == 2


def test_reload_manifest_endpoint(client: TestClient) -> None:
    response = client.post("/v1/reload-manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["reloaded"] is True
    assert body["documents"] >= 1


def test_ui_page(client: TestClient) -> None:
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 200
    assert "AI Repair Assistant" in response.text
    assert "Search only" in response.text
    assert "Diagnostic chat (streaming)" in response.text
    assert "Export JSON" in response.text
    assert "Cancel" in response.text
    assert "API key" not in response.text

    root = client.get("/", follow_redirects=False)
    assert root.status_code in {307, 308}
    assert "/ui" in root.headers.get("location", "")
