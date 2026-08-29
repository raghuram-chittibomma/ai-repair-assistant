"""Helpers for CI Postgres tests (review R38).

Uses ``REPAIR_TEST_DATABASE_URL`` only — never ``DATABASE_URL`` from
``.env.local``, so a local pytest run cannot touch the LAN corpus.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

import pytest

from repair_assistant.ingest.embeddings import DEFAULT_EMBEDDING_DIMS
from repair_assistant.ingest.parsed import ParsedChunk
from repair_assistant.ingest.store import Database, apply_migrations

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
