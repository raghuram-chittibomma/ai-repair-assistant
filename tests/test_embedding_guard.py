"""Embedding-model mismatch guard (review R16)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from repair_assistant.ingest.embeddings import (
    EmbeddingModelMismatch,
    assert_embedding_model,
    stored_embedding_models,
)


def test_assert_passes_when_index_is_empty() -> None:
    db = MagicMock()
    db.fetchall.return_value = []
    assert_embedding_model(db, "BAAI/bge-base-en-v1.5")


def test_assert_passes_when_stored_matches() -> None:
    db = MagicMock()
    db.fetchall.return_value = [("BAAI/bge-base-en-v1.5",)]
    assert stored_embedding_models(db) == ["BAAI/bge-base-en-v1.5"]
    assert_embedding_model(db, "BAAI/bge-base-en-v1.5")


def test_assert_fails_on_mismatch() -> None:
    db = MagicMock()
    db.fetchall.return_value = [("some-other-model",)]
    with pytest.raises(EmbeddingModelMismatch, match="ingest --all --force"):
        assert_embedding_model(db, "BAAI/bge-base-en-v1.5")
