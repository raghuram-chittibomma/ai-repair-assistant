"""Ingestion version lifecycle and cutover against a real pgvector (ADR-0047).

Skipped unless REPAIR_TEST_DATABASE_URL is set. CI starts pgvector/pgvector:pg17
and points that env at it.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from repair_assistant.ingest.parsed import ParsedDocument
from repair_assistant.retrieval.search import code_fetch, vector_fetch
from repair_assistant.retrieval.strategies import lexical_fetch, literal_fetch
from repair_assistant.semantic.lifecycle import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_READY,
    STATUS_SUPERSEDED,
    STRATEGY_SEMANTIC,
    STRATEGY_STRUCTURED,
    LifecycleError,
    abandon,
    activate,
    active_version,
    create_candidate,
    ensure_structured_active,
    get_version_by_id,
    list_versions,
    mark_ready,
    revert_to,
)
from tests.postgres_support import FixedEmbedder, make_chunk, upsert_structured

pytestmark = pytest.mark.postgres

LEGACY_TEXT = "Legacy chunk: drain pump resistance check at connector CN4."
SEMANTIC_TEXT = "Semantic rep: drain pump resistance check at connector CN4."


def _legacy_doc(db, doc_id: str, embedder: FixedEmbedder | None = None):
    return upsert_structured(
        db,
        doc_id,
        [
            make_chunk(
                doc_id=doc_id,
                chunk_id="p1-prose-legacy",
                text=LEGACY_TEXT,
                kind="prose",
                publication_number="SYNTH-CI-VER",
            )
        ],
        embedder,
    )


def _semantic_version(db, doc_id: str, *, text: str = SEMANTIC_TEXT):
    """A semantic candidate carrying one representation row."""
    version = create_candidate(
        db,
        doc_id,
        source_fingerprint="fp-semantic",
        segmenter_model="ci-fake-segmenter",
    )
    db.replace_chunks(
        doc_id,
        [
            make_chunk(
                doc_id=doc_id,
                chunk_id="u-drain-pump-overview",
                text=text,
                kind="prose",
                publication_number="SYNTH-CI-VER",
            )
        ],
        version_id=version.id,
    )
    db.commit()
    return version


# --- migration shape --------------------------------------------------------


def test_migration_creates_versions_units_and_view(pg_db) -> None:
    for table in ("ingestion_versions", "semantic_units", "semantic_proposals"):
        row = pg_db.fetchone(
            "SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)
        )
        assert row == (True,), f"{table} missing"
    view = pg_db.fetchone("SELECT to_regclass('public.active_chunks') IS NOT NULL")
    assert view == (True,)
    idx = pg_db.fetchone(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'ingestion_versions'
          AND indexname = 'ingestion_versions_one_active'
        """
    )
    assert idx is not None


def test_chunks_no_longer_unique_on_doc_and_chunk_id(pg_db) -> None:
    """Both representations of a promoted document coexist in `chunks`."""
    _legacy_doc(pg_db, "ci-ver-dual")
    version = create_candidate(pg_db, "ci-ver-dual", source_fingerprint="fp")
    # Same chunk_id as the legacy row, different version: must be allowed.
    pg_db.replace_chunks(
        "ci-ver-dual",
        [
            make_chunk(
                doc_id="ci-ver-dual",
                chunk_id="p1-prose-legacy",
                text="A different representation reusing the same chunk id.",
                publication_number="SYNTH-CI-VER",
            )
        ],
        version_id=version.id,
    )
    pg_db.commit()
    row = pg_db.fetchone(
        "SELECT count(*) FROM chunks WHERE doc_id = %s AND chunk_id = %s",
        ("ci-ver-dual", "p1-prose-legacy"),
    )
    assert row == (2,)


# --- legacy ingest is unchanged --------------------------------------------


def test_legacy_ingest_creates_structured_active_version(pg_db) -> None:
    version = _legacy_doc(pg_db, "ci-ver-legacy")
    assert version.strategy == STRATEGY_STRUCTURED
    assert version.status == STATUS_ACTIVE
    assert version.version == 1
    rows = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-legacy",)
    )
    assert [r[0] for r in rows] == ["p1-prose-legacy"]


def test_documents_can_use_different_strategies_simultaneously(pg_db) -> None:
    embedder = FixedEmbedder()
    _legacy_doc(pg_db, "ci-ver-stays-legacy", embedder)
    _legacy_doc(pg_db, "ci-ver-goes-semantic", embedder)
    semantic = _semantic_version(pg_db, "ci-ver-goes-semantic")
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)

    assert active_version(pg_db, "ci-ver-stays-legacy").strategy == STRATEGY_STRUCTURED
    assert active_version(pg_db, "ci-ver-goes-semantic").strategy == STRATEGY_SEMANTIC

    rows = pg_db.fetchall(
        "SELECT doc_id, chunk_id, strategy FROM active_chunks WHERE doc_id LIKE 'ci-ver-%%'"
    )
    by_doc = {r[0]: (r[1], r[2]) for r in rows}
    assert by_doc["ci-ver-stays-legacy"] == ("p1-prose-legacy", STRATEGY_STRUCTURED)
    assert by_doc["ci-ver-goes-semantic"] == ("u-drain-pump-overview", STRATEGY_SEMANTIC)


# --- safe cutover -----------------------------------------------------------


def test_legacy_stays_active_while_semantic_is_incomplete(pg_db) -> None:
    _legacy_doc(pg_db, "ci-ver-inflight")
    candidate = _semantic_version(pg_db, "ci-ver-inflight")
    assert candidate.status == STATUS_CANDIDATE

    active = active_version(pg_db, "ci-ver-inflight")
    assert active.strategy == STRATEGY_STRUCTURED
    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-inflight",)
    )
    assert [r[0] for r in visible] == ["p1-prose-legacy"]

    # A candidate cannot serve traffic even by mistake.
    with pytest.raises(LifecycleError):
        activate(pg_db, candidate.id)


def test_abandoned_proposal_leaves_legacy_active(pg_db) -> None:
    _legacy_doc(pg_db, "ci-ver-abandon")
    candidate = _semantic_version(pg_db, "ci-ver-abandon")
    abandon(pg_db, candidate.id)

    assert active_version(pg_db, "ci-ver-abandon").strategy == STRATEGY_STRUCTURED
    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-abandon",)
    )
    assert [r[0] for r in visible] == ["p1-prose-legacy"]


def test_cutover_supersedes_legacy_in_one_step(pg_db) -> None:
    legacy = _legacy_doc(pg_db, "ci-ver-cutover")
    semantic = _semantic_version(pg_db, "ci-ver-cutover")
    mark_ready(pg_db, semantic.id)
    activated = activate(pg_db, semantic.id)

    assert activated.status == STATUS_ACTIVE
    outgoing = get_version_by_id(pg_db, legacy.id)
    assert outgoing.status == STATUS_SUPERSEDED
    assert outgoing.superseded_by == semantic.id

    # Exactly one active version at every point, never zero.
    actives = pg_db.fetchall(
        "SELECT count(*) FROM ingestion_versions WHERE doc_id = %s AND status = 'active'",
        ("ci-ver-cutover",),
    )
    assert actives == [(1,)]


def test_duplicate_active_version_is_rejected_by_the_database(pg_db) -> None:
    _legacy_doc(pg_db, "ci-ver-dupe")
    with pytest.raises(psycopg.errors.UniqueViolation):
        # Bypasses the lifecycle helpers on purpose: the partial unique index is
        # the guardrail, not the Python.
        pg_db.execute(
            """
            INSERT INTO ingestion_versions (doc_id, version, strategy, status, source_fingerprint)
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("ci-ver-dupe", 99, STRATEGY_SEMANTIC, STATUS_ACTIVE, "fp"),
        )
    pg_db.rollback()


# --- superseded rows leave retrieval --------------------------------------


def test_superseded_legacy_chunks_leave_vector_and_lexical_search(pg_db) -> None:
    embedder = FixedEmbedder()
    _legacy_doc(pg_db, "ci-ver-search", embedder)

    query = embedder.embed(["drain pump resistance"])[0]
    before = vector_fetch(pg_db, query, limit=20, include_synthetic=True)
    assert any(h["chunk_id"] == "p1-prose-legacy" for h in before)
    lex_before = lexical_fetch(pg_db, "drain pump resistance", limit=20)
    assert any(h["chunk_id"] == "p1-prose-legacy" for h in lex_before)

    semantic = _semantic_version(pg_db, "ci-ver-search")
    need = pg_db.chunks_missing_embeddings("ci-ver-search", version_id=semantic.id)
    vectors = embedder.embed([t for _, t in need])
    pg_db.set_embeddings(
        "ci-ver-search",
        [(cid, vec) for (cid, _), vec in zip(need, vectors, strict=True)],
        embedder.model,
        version_id=semantic.id,
    )
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)

    after = vector_fetch(pg_db, query, limit=20, include_synthetic=True)
    ids = [h["chunk_id"] for h in after if h["doc_id"] == "ci-ver-search"]
    assert "p1-prose-legacy" not in ids
    assert ids == ["u-drain-pump-overview"], "no duplicate representations after cutover"

    lex_after = lexical_fetch(pg_db, "drain pump resistance", limit=20)
    lex_ids = [h["chunk_id"] for h in lex_after if h["doc_id"] == "ci-ver-search"]
    assert lex_ids == ["u-drain-pump-overview"]

    lit = literal_fetch(pg_db, "resistance at CN4", limit=20)
    lit_ids = [h["chunk_id"] for h in lit if h["doc_id"] == "ci-ver-search"]
    assert "p1-prose-legacy" not in lit_ids


def test_superseded_code_hits_leave_code_fetch(pg_db) -> None:
    upsert_structured(
        pg_db,
        "ci-ver-code",
        [
            make_chunk(
                doc_id="ci-ver-code",
                chunk_id="p1-table_row-legacy",
                text="F8E1 | Long fill | Check the water supply.",
                kind="table_row",
                error_codes=["F8E1"],
                publication_number="SYNTH-CI-VER-CODE",
            )
        ],
    )
    assert any(
        h["chunk_id"] == "p1-table_row-legacy" for h in code_fetch(pg_db, ["F8E1"], limit=20)
    )

    version = create_candidate(pg_db, "ci-ver-code", source_fingerprint="fp")
    pg_db.replace_chunks(
        "ci-ver-code",
        [
            make_chunk(
                doc_id="ci-ver-code",
                chunk_id="u-long-fill-facts",
                text="F8E1 long fill: check water supply, inlet valve, and flowmeter.",
                kind="prose",
                error_codes=["F8E1"],
                publication_number="SYNTH-CI-VER-CODE",
            )
        ],
        version_id=version.id,
    )
    pg_db.commit()
    mark_ready(pg_db, version.id)
    activate(pg_db, version.id)

    ids = [h["chunk_id"] for h in code_fetch(pg_db, ["F8E1"], limit=20)]
    assert "p1-table_row-legacy" not in ids
    assert "u-long-fill-facts" in ids


# --- rollback ---------------------------------------------------------------


def test_revert_restores_legacy_without_touching_the_source_document(pg_db) -> None:
    legacy = _legacy_doc(pg_db, "ci-ver-revert")
    doc_before = pg_db.fetchone(
        "SELECT doc_id, content_fingerprint, source_filename FROM documents WHERE doc_id = %s",
        ("ci-ver-revert",),
    )

    semantic = _semantic_version(pg_db, "ci-ver-revert")
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)
    reverted = revert_to(pg_db, "ci-ver-revert", legacy.version)

    assert reverted.id == legacy.id
    assert reverted.status == STATUS_ACTIVE
    assert get_version_by_id(pg_db, semantic.id).status == STATUS_SUPERSEDED

    # Superseded semantic rows are still stored, just not selected.
    stored = pg_db.fetchone(
        "SELECT count(*) FROM chunks WHERE doc_id = %s", ("ci-ver-revert",)
    )
    assert stored == (2,)
    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-revert",)
    )
    assert [r[0] for r in visible] == ["p1-prose-legacy"]

    doc_after = pg_db.fetchone(
        "SELECT doc_id, content_fingerprint, source_filename FROM documents WHERE doc_id = %s",
        ("ci-ver-revert",),
    )
    assert doc_after == doc_before


def test_revert_then_reactivate_semantic_keeps_history(pg_db) -> None:
    legacy = _legacy_doc(pg_db, "ci-ver-roundtrip")
    semantic = _semantic_version(pg_db, "ci-ver-roundtrip")
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)
    revert_to(pg_db, "ci-ver-roundtrip", legacy.version)
    activate(pg_db, semantic.id)

    versions = list_versions(pg_db, "ci-ver-roundtrip")
    assert [(v.version, v.status) for v in versions] == [
        (1, STATUS_SUPERSEDED),
        (2, STATUS_ACTIVE),
    ]


# --- the routine-reingest guard -------------------------------------------


def test_structured_ingest_refuses_to_clobber_an_active_semantic_version(pg_db) -> None:
    _legacy_doc(pg_db, "ci-ver-guard")
    semantic = _semantic_version(pg_db, "ci-ver-guard")
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)

    with pytest.raises(LifecycleError) as excinfo:
        ensure_structured_active(pg_db, "ci-ver-guard", source_fingerprint="fp-new")
    assert "ingestion-revert" in str(excinfo.value)
    pg_db.rollback()

    assert active_version(pg_db, "ci-ver-guard").strategy == STRATEGY_SEMANTIC


def test_ingest_pipeline_skips_a_semantic_document_with_a_loud_detail(pg_db) -> None:
    from repair_assistant.ingest.embeddings import NullEmbedder
    from repair_assistant.ingest.pipeline import _ingest_one

    _legacy_doc(pg_db, "ci-ver-pipeline")
    semantic = _semantic_version(pg_db, "ci-ver-pipeline")
    mark_ready(pg_db, semantic.id)
    activate(pg_db, semantic.id)

    chunks = [
        make_chunk(
            doc_id="ci-ver-pipeline",
            chunk_id="p1-prose-legacy",
            text="Re-parsed legacy text that must not reach the database.",
            publication_number="SYNTH-CI-VER",
        )
    ]
    parsed = ParsedDocument(
        doc_id="ci-ver-pipeline",
        path=Path("ci"),
        meta={"publication_number": "SYNTH-CI-VER", "extractor": "ci"},
        chunks=chunks,
    )
    stats = _ingest_one(
        pg_db, parsed, NullEmbedder(), force=True, corpus_sha256=None
    )
    assert stats.status == "skipped"
    assert "ingestion-revert" in stats.detail

    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-pipeline",)
    )
    assert [r[0] for r in visible] == ["u-drain-pump-overview"]


def test_ready_version_is_not_yet_searchable(pg_db) -> None:
    _legacy_doc(pg_db, "ci-ver-ready")
    semantic = _semantic_version(pg_db, "ci-ver-ready")
    ready = mark_ready(pg_db, semantic.id)
    assert ready.status == STATUS_READY

    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", ("ci-ver-ready",)
    )
    assert [r[0] for r in visible] == ["p1-prose-legacy"]
