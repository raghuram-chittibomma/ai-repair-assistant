"""Bake-off rerank helper (no model download)."""

from __future__ import annotations

import pytest

from repair_assistant.retrieval.rerank import rerank_hits


def test_rerank_hits_orders_by_injected_scores() -> None:
    hits = [
        {"doc_id": "a", "chunk_id": "1", "text": "first", "score": 0.9},
        {"doc_id": "b", "chunk_id": "2", "text": "second", "score": 0.8},
        {"doc_id": "c", "chunk_id": "3", "text": "third", "score": 0.7},
    ]

    def score_fn(pairs):
        assert [p[1] for p in pairs] == ["first", "second", "third"]
        return [0.1, 0.9, 0.2]

    out = rerank_hits("what is F6E1?", hits, limit=2, score_fn=score_fn)
    assert [h["doc_id"] for h in out] == ["b", "c"]
    assert out[0]["score"] == 0.9


def test_rerank_hits_empty() -> None:
    assert rerank_hits("q", [], limit=8) == []


def test_rerank_hits_rejects_score_length_mismatch() -> None:
    hits = [{"doc_id": "a", "chunk_id": "1", "text": "x"}]
    with pytest.raises(ValueError, match="one score per hit"):
        rerank_hits("q", hits, limit=1, score_fn=lambda _pairs: [])


def test_rerank_model_name_defaults_to_base(monkeypatch: pytest.MonkeyPatch) -> None:
    from repair_assistant.retrieval.rerank import DEFAULT_RERANK_MODEL, rerank_model_name

    monkeypatch.delenv("REPAIR_RERANK_MODEL", raising=False)
    assert DEFAULT_RERANK_MODEL == "BAAI/bge-reranker-base"
    assert rerank_model_name() == DEFAULT_RERANK_MODEL
