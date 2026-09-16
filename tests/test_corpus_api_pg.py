"""Corpus review API against pgvector for PDF-native semantic units (ADR-0049).

Skipped unless REPAIR_TEST_DATABASE_URL is set.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repair_assistant.api.corpus_routes import build_corpus_router
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.semantic.lifecycle import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_READY,
    STATUS_SUPERSEDED,
    STRATEGY_SEMANTIC,
    STRATEGY_STRUCTURED,
    active_version,
)
from tests.postgres_support import FixedEmbedder, make_chunk, upsert_structured
from tests.semantic_fixtures import (
    GOOD_UNITS,
    FakeRepresenter,
    FakeSegmenter,
    patch_pdf_segmentation,
    write_stub_pdf,
)

pytestmark = pytest.mark.postgres

DOC_ID = "ci-semantic-doc"


class Recorder:
    def __init__(self, **kwargs) -> None:
        self.inner = FakeRepresenter(**kwargs)
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.inner.complete(system, user)


class CountingEmbedder(FixedEmbedder):
    def __init__(self) -> None:
        self.batches = 0
        self.texts = 0

    def embed(self, texts):
        batch = list(texts)
        if batch:
            self.batches += 1
            self.texts += len(batch)
        return super().embed(batch)


@pytest.fixture
def corpus_api(pg_db, tmp_path: Path, monkeypatch):
    pdf = write_stub_pdf(tmp_path / "corpus" / "documents" / "SYNTH-CI-SEMA.pdf")
    patch_pdf_segmentation(monkeypatch, pdf, pages=3)
    document = Document(
        path=tmp_path / "manifest" / f"{DOC_ID}.yaml",
        data={
            "doc_id": DOC_ID,
            "title": "CI Service Manual",
            "doc_type": "service_manual",
            "publication_number": "SYNTH-CI-SEM",
            "revision": "A",
            "provenance": {"local_filename": "SYNTH-CI-SEMA.pdf"},
        },
    )
    manifest = Manifest(documents=[document], excluded=[], root=tmp_path)

    embedder = CountingEmbedder()
    segmenter = FakeSegmenter({"units": GOOD_UNITS})
    representer = Recorder()

    upsert_structured(
        pg_db,
        DOC_ID,
        [
            make_chunk(
                doc_id=DOC_ID,
                chunk_id="p1-prose-legacy",
                text="Legacy chunk about the drain pump.",
                publication_number="SYNTH-CI-SEM",
            )
        ],
        embedder,
    )

    app = FastAPI()
    app.include_router(
        build_corpus_router(
            get_db=lambda: pg_db,
            require_api_key=lambda: None,
            manifest=lambda: manifest,
            repo_root=lambda: tmp_path,
            embedder=lambda: embedder,
            segmenter=lambda: segmenter,
            representer=lambda: representer,
        )
    )
    client = TestClient(app)
    client.embedder = embedder
    client.representer = representer
    return client


def _propose(client, **body) -> dict:
    res = client.post(f"/v1/corpus/documents/{DOC_ID}/semantic/propose", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _review(client, version: int) -> dict:
    res = client.get(f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}")
    assert res.status_code == 200, res.text
    return res.json()


def test_pdf_route_streams_bytes(corpus_api) -> None:
    res = corpus_api.get(f"/v1/corpus/documents/{DOC_ID}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content[:4] == b"%PDF"


def test_propose_defers_reps_until_approve(corpus_api) -> None:
    body = _propose(corpus_api)
    assert body["status"] == "proposed"
    assert body["units"] == 2
    assert body["representations"] == 0
    assert corpus_api.representer.calls == 0

    version = body["version"]
    payload = _review(corpus_api, version)
    assert payload["status"] == STATUS_CANDIDATE
    assert payload["pdf_url"] == f"/v1/corpus/documents/{DOC_ID}/pdf"
    assert payload["page_count"] == 3
    assert payload["anchors"] == []
    assert len(payload["units"]) == 2
    assert payload["units"][0]["page_start"] == 1
    assert "WARNING" in payload["units"][0]["source_text"]


def test_patch_page_markers_and_approve_activate(corpus_api) -> None:
    version = _propose(corpus_api)["version"]
    unit_key = _review(corpus_api, version)["units"][0]["unit_key"]

    patched = corpus_api.patch(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{unit_key}",
        json={"start_page": 1, "end_page": 2, "start_y": 0.1, "end_y": 0.9},
    )
    assert patched.status_code == 200, patched.text

    for unit in _review(corpus_api, version)["units"]:
        corpus_api.patch(
            f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{unit['unit_key']}",
            json={"review_status": "approved"},
        )

    approved = corpus_api.post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/approve"
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == STATUS_READY
    assert corpus_api.representer.calls >= 2

    activated = corpus_api.post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/activate"
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == STATUS_ACTIVE
    assert activated.json()["active_strategy"] == STRATEGY_SEMANTIC

    listed = corpus_api.get("/v1/corpus/documents").json()["documents"][0]
    assert listed["review_version"] == version
    assert listed["review_status"] == STATUS_ACTIVE
    assert listed["review_editable"] is False

    blocked = corpus_api.patch(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{unit_key}",
        json={"title": "should fail"},
    )
    assert blocked.status_code == 409
    assert "Revise" in blocked.json()["detail"]

    revised = corpus_api.post(f"/v1/corpus/documents/{DOC_ID}/semantic/revise")
    assert revised.status_code == 200, revised.text
    assert revised.json()["status"] == "candidate"
    fork = revised.json()["version"]
    assert fork != version

    listed = corpus_api.get("/v1/corpus/documents").json()["documents"][0]
    assert listed["review_version"] == fork
    assert listed["review_status"] == STATUS_CANDIDATE
    assert listed["review_editable"] is True
    assert listed["active_version"] == version

    fork_units = _review(corpus_api, fork)["units"]
    assert len(fork_units) == 2
    patched_fork = corpus_api.patch(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{fork}/units/"
        f"{fork_units[0]['unit_key']}",
        json={"title": "Edited after revise"},
    )
    assert patched_fork.status_code == 200, patched_fork.text


def test_split_merge_and_pdf_markers(corpus_api) -> None:
    version = _propose(corpus_api)["version"]
    unit_key = _review(corpus_api, version)["units"][0]["unit_key"]

    split = corpus_api.post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{unit_key}/split",
        json={"at_page": 2, "at_y": 0.0, "title": "Tail"},
    )
    assert split.status_code == 200, split.text
    assert len(split.json()["changed"]) == 2

    keys = [u["unit_key"] for u in _review(corpus_api, version)["units"]]
    merged = corpus_api.post(
        f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{keys[0]}/merge",
        json={"with_unit": "next"},
    )
    assert merged.status_code == 200, merged.text


def test_revert_restores_structured(corpus_api, pg_db) -> None:
    version = _propose(corpus_api)["version"]
    for unit in _review(corpus_api, version)["units"]:
        corpus_api.patch(
            f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/units/{unit['unit_key']}",
            json={"review_status": "approved"},
        )
    assert (
        corpus_api.post(
            f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/approve"
        ).status_code
        == 200
    )
    assert (
        corpus_api.post(
            f"/v1/corpus/documents/{DOC_ID}/semantic/versions/{version}/activate"
        ).status_code
        == 200
    )

    reverted = corpus_api.post(
        f"/v1/corpus/documents/{DOC_ID}/revert", json={}
    )
    assert reverted.status_code == 200, reverted.text
    current = active_version(pg_db, DOC_ID)
    assert current is not None
    assert current.strategy == STRATEGY_STRUCTURED
    assert current.status == STATUS_ACTIVE

    semantic = [
        v
        for v in corpus_api.get("/v1/corpus/documents").json()["documents"][0][
            "versions"
        ]
        if v["strategy"] == STRATEGY_SEMANTIC
    ]
    assert semantic[0]["status"] == STATUS_SUPERSEDED
