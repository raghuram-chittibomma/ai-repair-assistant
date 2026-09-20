"""Unit tests for corpus assist sessions and suggestion parse (ADR-0053)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repair_assistant.api.assist_sessions import AssistSessionStore
from repair_assistant.api.corpus_routes import build_corpus_router
from repair_assistant.semantic.assist import (
    AssistError,
    AssistSuggestion,
    parse_assist_response,
)
from repair_assistant.semantic.units import SemanticUnit


def test_parse_assist_response_ok() -> None:
    raw = """{
      "rationale": "Tighten facts.",
      "overview": "Door lock test procedure.",
      "facts": ["F5E2 door lock", "TEST #4"],
      "questions": ["What does F5E2 mean?"]
    }"""
    suggestion = parse_assist_response(raw)
    assert suggestion.overview.startswith("Door lock")
    assert "F5E2 door lock" in suggestion.facts
    assert suggestion.questions == ["What does F5E2 mean?"]


def test_parse_assist_response_rejects_bad_json() -> None:
    with pytest.raises(AssistError):
        parse_assist_response("not json")


def test_assist_session_store_ttl_and_410_shape() -> None:
    store = AssistSessionStore(ttl_seconds=3600, max_sessions=2)
    a = store.create(doc_id="doc-a", version=1, unit_key="u1")
    b = store.create(doc_id="doc-b", version=2)
    assert store.count() == 2
    store.create(doc_id="doc-c", version=3)  # evicts oldest
    assert store.count() == 2
    with pytest.raises(KeyError):
        store.get(a.session_id)
    assert store.get(b.session_id).doc_id == "doc-b"
    assert store.delete(b.session_id) is True
    with pytest.raises(KeyError):
        store.get(b.session_id)


class _FakeAssist:
    last_kwargs: dict = {}

    def complete(self, system: str, user: str, **kwargs) -> str:
        type(self).last_kwargs = dict(kwargs)
        assert "source_text" in user
        assert "Reviewer request" in user
        assert "Document context:" in user
        return (
            '{"rationale":"ok","overview":"Short overview.",'
            '"facts":["code F5E2"],"questions":["What is F5E2?"]}'
        )


def test_run_assist_turn_appends_memory() -> None:
    from repair_assistant.semantic.assist import DocumentContext, run_assist_turn

    store = AssistSessionStore()
    session = store.create(doc_id="doc-a", version=1, unit_key="u1")
    unit = SemanticUnit(
        unit_key="u1",
        ordinal=0,
        title="Door lock",
        unit_type="procedure",
        page_start=1,
        page_end=2,
        section_path=[],
        source_text="F5E2 indicates a door lock fault. Run TEST #4.",
        source_span=["p.1"],
        content_hash="abc",
        start_y=0.0,
        end_y=1.0,
    )
    suggestion = run_assist_turn(
        session=session,
        unit=unit,
        message="Shorten the overview",
        draft={"overview": "Long overview…", "facts": [], "questions": []},
        llm=_FakeAssist(),
        document=DocumentContext(
            doc_id="doc-a",
            title="Service manual",
            doc_type="service_manual",
            publication_number="W11169652",
            revision="B",
        ),
    )
    assert isinstance(suggestion, AssistSuggestion)
    assert suggestion.overview == "Short overview."
    assert len(session.turns) == 2
    assert session.turns[0].role == "user"
    assert session.turns[1].suggestions is not None


def test_prepare_unit_attachments_writes_pdf_slice(tmp_path) -> None:
    import fitz

    from repair_assistant.semantic.assist import prepare_unit_attachments

    src = tmp_path / "manual.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(str(src))
    doc.close()

    unit = SemanticUnit(
        unit_key="u1",
        ordinal=0,
        title="t",
        unit_type="other",
        page_start=2,
        page_end=3,
        section_path=[],
        source_text="body",
        source_span=[],
        content_hash="h",
    )
    atts = prepare_unit_attachments(
        pdf_path=src,
        unit=unit,
        doc_id="doc-a",
        looks_scanned=False,
    )
    assert atts.modality == "pdf"
    assert atts.pdf_path is not None and atts.pdf_path.is_file()
    sliced = fitz.open(str(atts.pdf_path))
    assert sliced.page_count == 2
    sliced.close()
    atts.cleanup()
    assert atts.pdf_path is None or not atts.pdf_path.is_file()


def test_run_assist_turn_passes_pdf_path(tmp_path) -> None:
    from repair_assistant.semantic.assist import (
        AssistAttachments,
        DocumentContext,
        run_assist_turn,
    )

    pdf = tmp_path / "unit.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    store = AssistSessionStore()
    session = store.create(doc_id="doc-a", version=1)
    unit = SemanticUnit(
        unit_key="u1",
        ordinal=0,
        title="t",
        unit_type="other",
        page_start=1,
        page_end=1,
        section_path=[],
        source_text="body",
        source_span=[],
        content_hash="h",
    )
    # Skip cleanup unlink of our fixture by using a non-temp path without temp_dir
    atts = AssistAttachments(pdf_path=pdf, modality="pdf", temp_dir=None)
    # Prevent cleanup from deleting the fixture used only for path check
    atts.cleanup = lambda: None  # type: ignore[method-assign]

    _FakeAssist.last_kwargs = {}
    run_assist_turn(
        session=session,
        unit=unit,
        message="hi",
        draft=None,
        llm=_FakeAssist(),
        document=DocumentContext(doc_id="doc-a", title="T"),
        attachments=atts,
    )
    assert _FakeAssist.last_kwargs.get("pdf_path") == pdf


def test_assist_session_routes_410_without_db(monkeypatch) -> None:
    """Unknown session id → 410 without needing Postgres."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from repair_assistant.corpus.manifest import Document, Manifest

    root = Path(".")
    manifest = Manifest(
        documents=[
            Document(
                data={
                    "doc_id": "ci-doc",
                    "title": "CI",
                    "doc_type": "service_manual",
                    "publication_number": "X",
                    "revision": "A",
                    "provenance": {"local_filename": "x.pdf"},
                },
                path=root / "ci-doc.yaml",
            )
        ],
        excluded=[],
        root=root,
    )
    store = AssistSessionStore()
    app = FastAPI()
    app.include_router(
        build_corpus_router(
            get_db=lambda: MagicMock(),
            require_api_key=lambda: None,
            manifest=lambda: manifest,
            repo_root=lambda: root,
            embedder=MagicMock,
            assist_store=store,
            assist_client=lambda: _FakeAssist(),
        )
    )
    client = TestClient(app)

    class _Ver:
        id = 9
        version = 1
        strategy = "semantic_llm"
        status = "ready"

    monkeypatch.setattr(
        "repair_assistant.api.corpus_routes.get_version",
        lambda db, doc_id, version: _Ver(),
    )
    monkeypatch.setattr(
        "repair_assistant.semantic.store.get_unit",
        lambda db, version_id, unit_key: SemanticUnit(
            unit_key=unit_key,
            ordinal=0,
            title="t",
            unit_type="other",
            page_start=1,
            page_end=1,
            section_path=[],
            source_text="hello",
            source_span=[],
            content_hash="h",
            start_y=0.0,
            end_y=1.0,
        ),
    )
    res = client.post(
        "/v1/corpus/documents/ci-doc/semantic/versions/1/assist/sessions/missing/message",
        json={"unit_key": "u1", "message": "hi"},
    )
    assert res.status_code == 410
