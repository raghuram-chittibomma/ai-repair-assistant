"""Helpers for CI Postgres tests (review R38).

Uses ``REPAIR_TEST_DATABASE_URL`` only — never ``DATABASE_URL`` from
``.env.local``, so a local pytest run cannot touch the LAN corpus.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from repair_assistant.ingest.embeddings import DEFAULT_EMBEDDING_DIMS
from repair_assistant.ingest.parsed import ParsedChunk, ParsedDocument
from repair_assistant.ingest.store import Database, apply_migrations
from repair_assistant.semantic.lifecycle import (
    IngestionVersion,
    ensure_structured_active,
)

TEST_DATABASE_URL_ENV = "REPAIR_TEST_DATABASE_URL"


class FixedEmbedder:
    """Deterministic 768-d vectors so CI never downloads BGE."""

    model = "ci-fixed-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i, _text in enumerate(texts):
            vec = [0.0] * DEFAULT_EMBEDDING_DIMS
            vec[0] = 1.0
            vec[1] = 0.01 * i
            out.append(vec)
        return out


def test_database_url() -> str | None:
    return os.environ.get(TEST_DATABASE_URL_ENV, "").strip() or None


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def make_chunk(
    *,
    doc_id: str,
    chunk_id: str,
    text: str,
    page: int | None = 1,
    kind: str = "prose",
    error_codes: list[str] | None = None,
    publication_number: str | None = "SYNTH-CI-1",
    revision: str | None = "A",
) -> ParsedChunk:
    return ParsedChunk(
        chunk_id=chunk_id,
        text=text,
        page=page,
        kind=kind,
        error_codes=list(error_codes or []),
        language="en-US",
        doc_id=doc_id,
        publication_number=publication_number,
        revision=revision,
        metadata={"ci": True},
        content_hash=_hash(text),
    )


def upsert_structured(
    db: Database,
    doc_id: str,
    chunks: list[ParsedChunk],
    embedder: FixedEmbedder | None = None,
    *,
    meta: dict | None = None,
) -> IngestionVersion:
    """Ingest chunks as the document's structured active version (ADR-0047)."""
    parsed = ParsedDocument(
        doc_id=doc_id,
        path=Path("ci"),
        meta=meta
        or {
            "publication_number": chunks[0].publication_number if chunks else None,
            "extractor": "ci",
        },
        chunks=chunks,
    )
    db.upsert_document(parsed, corpus_sha256=None)
    version = ensure_structured_active(
        db, doc_id, source_fingerprint=parsed.content_fingerprint
    )
    db.replace_chunks(doc_id, chunks, version_id=version.id)
    if embedder is not None:
        vectors = embedder.embed([c.text for c in chunks])
        db.set_embeddings(
            doc_id,
            [(c.chunk_id, v) for c, v in zip(chunks, vectors, strict=True)],
            embedder.model,
            version_id=version.id,
        )
    db.commit()
    return version


@pytest.fixture
def pg_db() -> Iterator[Database]:
    url = test_database_url()
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is unset")
    db = Database(url)
    try:
        apply_migrations(db)
        db.execute("TRUNCATE documents CASCADE")
        db.commit()
        yield db
    finally:
        db.close()
