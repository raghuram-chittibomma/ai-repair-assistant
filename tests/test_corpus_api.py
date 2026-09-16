"""Corpus review routes that do not need a database (ADR-0049).

Guard paths: missing PDF, missing LLM config, UI contract for the PDF.js board.
Postgres-backed behaviour lives in tests/test_corpus_api_pg.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repair_assistant.api.corpus_routes import build_corpus_router
from repair_assistant.corpus.manifest import Document, Manifest
from tests.semantic_fixtures import FakeSegmenter, write_parsed, write_stub_pdf

DOC_ID = "ci-semantic-doc"


def _manifest(root: Path) -> Manifest:
    return Manifest(
        documents=[
            Document(
                data={
                    "doc_id": DOC_ID,
                    "title": "CI Service Manual",
                    "doc_type": "service_manual",
                    "publication_number": "SYNTH-CI-SEM",
                    "revision": "A",
                    "provenance": {"local_filename": "SYNTH-CI-SEMA.pdf"},
                },
                path=root / "manifest" / f"{DOC_ID}.yaml",
            )
        ],
        excluded=[],
        root=root,
    )


def _client(
    root: Path,
    *,
    db: MagicMock | None = None,
    segmenter=None,
    representer=None,
) -> TestClient:
    from repair_assistant.ingest.embeddings import NullEmbedder

    database = db or MagicMock()
    if db is None:
        database.fetchall.return_value = []
        database.fetchone.return_value = None
    app = FastAPI()
    app.include_router(
        build_corpus_router(
            get_db=lambda: database,
            require_api_key=lambda: None,
            manifest=lambda: _manifest(root),
            repo_root=lambda: root,
            embedder=NullEmbedder,
            segmenter=segmenter,
            representer=representer,
        )
    )
    return TestClient(app)


def test_the_list_reports_a_document_with_no_ingestion_version(tmp_path: Path) -> None:
    write_parsed(tmp_path / "corpus", DOC_ID)
    body = _client(tmp_path).get("/v1/corpus/documents").json()

    assert len(body["documents"]) == 1
    doc = body["documents"][0]
    assert doc["doc_id"] == DOC_ID
    assert doc["title"] == "CI Service Manual"
    assert doc["parsed"] is True
    assert doc["ingested"] is False
    assert doc["active_strategy"] is None
    assert doc["versions"] == []


def test_a_document_without_pdf_cannot_be_segmented(tmp_path: Path) -> None:
    res = _client(tmp_path, segmenter=lambda: FakeSegmenter({"units": []})).post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/propose", json={}
    )
    assert res.status_code == 409
    assert "PDF not found" in res.json()["detail"]


def test_pdf_route_streams_manufacturer_bytes(tmp_path: Path) -> None:
    write_stub_pdf(tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf")
    res = _client(tmp_path).get(f"/v1/corpus/documents/{DOC_ID}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content[:5] == b"%PDF-"


def test_pdf_route_is_409_when_file_missing(tmp_path: Path) -> None:
    res = _client(tmp_path).get(f"/v1/corpus/documents/{DOC_ID}/pdf")
    assert res.status_code == 409
    assert "PDF not found" in res.json()["detail"]


def test_pdf_route_rejects_non_pdf_corpus_bytes(tmp_path: Path) -> None:
    path = tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"From: saved\r\nMIME-Version: 1.0\r\n")
    res = _client(tmp_path).get(f"/v1/corpus/documents/{DOC_ID}/pdf")
    assert res.status_code == 409
    assert "not a PDF" in res.json()["detail"]


def test_a_document_outside_the_manifest_is_a_404(tmp_path: Path) -> None:
    res = _client(tmp_path).post("/v1/corpus/documents/nope/semantic/propose", json={})
    assert res.status_code == 404
    assert "manifest" in res.json()["detail"]


@pytest.mark.parametrize(
    ("segmenter", "missing"),
    [
        (None, "semantic segmentation"),
    ],
)
def test_propose_refuses_when_the_llm_is_not_configured(
    tmp_path: Path, segmenter, missing: str
) -> None:
    write_stub_pdf(tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf")
    res = _client(tmp_path, segmenter=segmenter).post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/propose", json={}
    )
    assert res.status_code == 503
    assert missing in res.json()["detail"]


def test_propose_does_not_require_a_representer(tmp_path: Path) -> None:
    """Representations are generated on approve, not at propose time."""
    write_stub_pdf(tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf")
    res = _client(
        tmp_path,
        segmenter=lambda: FakeSegmenter({"units": []}),
        representer=None,
    ).post(f"/v1/corpus/documents/{DOC_ID}/semantic/propose", json={})
    assert res.status_code != 503
    assert "representation" not in (res.json().get("detail") or "").lower()


def test_a_missing_api_key_surfaces_as_503_not_500(tmp_path: Path) -> None:
    write_stub_pdf(tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf")

    def no_key():
        raise RuntimeError("SEMANTIC_OPENAI_API_KEY is not set")

    res = _client(tmp_path, segmenter=no_key).post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/propose", json={}
    )
    assert res.status_code == 503
    assert "SEMANTIC_OPENAI_API_KEY" in res.json()["detail"]


def test_an_unknown_version_is_a_404(tmp_path: Path) -> None:
    write_parsed(tmp_path / "corpus", DOC_ID)
    res = _client(tmp_path).get(f"/v1/corpus/documents/{DOC_ID}/semantic/versions/9")
    assert res.status_code == 404
    assert "no version 9" in res.json()["detail"]


def test_revert_on_a_document_with_no_versions_is_a_404(tmp_path: Path) -> None:
    res = _client(tmp_path).post(f"/v1/corpus/documents/{DOC_ID}/revert", json={})
    assert res.status_code == 404
    assert "no ingestion versions" in res.json()["detail"]


def _page() -> str:
    path = Path("src/repair_assistant/api/static/corpus.html")
    return path.read_text(encoding="utf-8")


def test_the_review_page_uses_pdf_js_and_corpus_routes() -> None:
    page = _page()
    assert "/v1/corpus/documents" in page
    assert "/pdf" in page
    assert "pdfjsLib" in page
    assert "/v1/ask" not in page
    assert "/v1/diagnose" not in page


def test_the_review_page_supports_marker_drag_and_approve() -> None:
    page = _page()
    assert "beginDrag" in page
    assert "Propose semantic" in page
    assert "Finalizing" in page
    assert "btn-finalize" in page
    assert "Activate" in page
    assert ">Approve<" in page or 'Approved' in page
    assert "Mark approved" not in page
    assert "Join next" in page
    assert "Join prev" in page
    assert "Add unit" in page
    assert "splitAtClick" in page
    assert "Split at mid" not in page
    assert "pointerToPageY" in page
    assert "scrollToUnit" in page
    assert "selectUnit" in page


def test_the_review_page_disables_propose_while_busy_or_open() -> None:
    page = _page()
    assert "syncActionButtons" in page
    assert "state.proposing" in page
    assert "hasBoard" in page
    assert "btn-revise" in page
    assert "/semantic/revise" in page
    assert "review_editable" in page
    assert "Live approved markers" in page


def test_the_chat_ui_does_not_reach_into_the_review_api() -> None:
    chat = Path("src/repair_assistant/api/static/index.html").read_text(encoding="utf-8")
    assert "/v1/corpus" not in chat
    assert "/ui/corpus" not in chat
