"""Execute retrieval SQL against a real pgvector (review R38).

Skipped unless REPAIR_TEST_DATABASE_URL is set. CI starts pgvector/pgvector:pg17
and points that env at it. Local pytest without the env stays offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repair_assistant.ingest.embeddings import (
    EmbeddingModelMismatch,
    assert_embedding_model,
    clear_embeddings_for_other_models,
)
from repair_assistant.ingest.parsed import ParsedDocument
from repair_assistant.retrieval.search import code_fetch, connector_fetch, vector_fetch
from repair_assistant.retrieval.synthetic import ensure_synthetic_ingested
from tests.postgres_support import FixedEmbedder, make_chunk

pytestmark = pytest.mark.postgres


def _upsert(db, doc_id: str, chunks, embedder: FixedEmbedder | None = None) -> None:
    parsed = ParsedDocument(
        doc_id=doc_id,
        path=Path("ci"),
        meta={"publication_number": chunks[0].publication_number, "extractor": "ci"},
        chunks=chunks,
    )
    db.upsert_document(parsed, corpus_sha256=None)
    db.replace_chunks(doc_id, chunks)
    if embedder is not None:
        vectors = embedder.embed([c.text for c in chunks])
        db.set_embeddings(
            doc_id,
            [(c.chunk_id, v) for c, v in zip(chunks, vectors, strict=True)],
            embedder.model,
        )
    db.commit()


def test_migrations_create_pgvector_chunks(pg_db) -> None:
    row = pg_db.fetchone(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    )
    assert row is not None
    count = pg_db.fetchone("SELECT count(*) FROM chunks")
    assert count == (0,)


def test_migrations_create_trigram_gin(pg_db) -> None:
    """Review R15: pg_trgm + GIN so side-door `text ~*` is not a seq scan."""
    ext = pg_db.fetchone("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
    assert ext is not None
    idx = pg_db.fetchone(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'chunks' AND indexname = 'chunks_text_trgm_gin'
        """
    )
    assert idx is not None


def test_synthetic_ingest_and_vector_fetch_excludes_synth_by_default(pg_db) -> None:
    embedder = FixedEmbedder()
    touched = ensure_synthetic_ingested(pg_db, embedder)
    assert touched
    query = embedder.embed(["drum cleaner"])[0]
    hidden = vector_fetch(pg_db, query, limit=8, include_synthetic=False)
    assert all(not h["doc_id"].startswith("synth-") for h in hidden)
    shown = vector_fetch(pg_db, query, limit=8, include_synthetic=True)
    assert any(h["doc_id"].startswith("synth-") for h in shown)
    assert shown[0]["score"] > 0


def test_code_fetch_uses_array_overlap_and_spaced_regex(pg_db) -> None:
    _upsert(
        pg_db,
        "ci-code-doc",
        [
            make_chunk(
                doc_id="ci-code-doc",
                chunk_id="meta",
                text="Door lock fault table row.",
                kind="table_row",
                error_codes=["F5E2"],
                publication_number="SYNTH-CI-CODE",
            ),
            make_chunk(
                doc_id="ci-code-doc",
                chunk_id="spaced",
                text="MindTouch title: F5 E2 lid switch article body.",
                kind="article",
                error_codes=[],
                publication_number="SYNTH-CI-CODE",
            ),
        ],
    )
    hits = code_fetch(pg_db, ["F5E2"], limit=10)
    ids = {h["chunk_id"] for h in hits}
    assert "meta" in ids
    assert "spaced" in ids


def test_connector_fetch_neighbour_join(pg_db) -> None:
    neighbour = (
        "The motor stator harness lands on connector J36 at the ACU. "
        "This prose is long enough to pass the sixty-character neighbour floor."
    )
    assert len(neighbour) >= 60
    _upsert(
        pg_db,
        "ci-j36-doc",
        [
            make_chunk(
                doc_id="ci-j36-doc",
                chunk_id="cell",
                text="J36 | -1",
                page=4,
                kind="table_row",
                publication_number="SYNTH-CI-J36",
            ),
            make_chunk(
                doc_id="ci-j36-doc",
                chunk_id="context",
                text=neighbour,
                page=4,
                kind="prose",
                publication_number="SYNTH-CI-J36",
            ),
        ],
    )
    hits = connector_fetch(pg_db, ["J36"], limit=10)
    ids = {h["chunk_id"] for h in hits}
    assert "cell" in ids
    assert "context" in ids


def test_embedding_model_guard_and_force_clear(pg_db) -> None:
    embedder = FixedEmbedder()
    chunk = make_chunk(doc_id="ci-embed", chunk_id="e1", text="Door lock connector.")
    _upsert(pg_db, "ci-embed", [chunk], embedder=embedder)
    assert_embedding_model(pg_db, embedder.model)
    with pytest.raises(EmbeddingModelMismatch):
        assert_embedding_model(pg_db, "BAAI/bge-base-en-v1.5")
    cleared = clear_embeddings_for_other_models(pg_db, "BAAI/bge-base-en-v1.5")
    pg_db.commit()
    assert cleared == 1
    assert_embedding_model(pg_db, "BAAI/bge-base-en-v1.5")
