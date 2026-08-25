"""Unit tests for retrieval grading helpers (no Postgres)."""

from __future__ import annotations

from repair_assistant.retrieval.bench import grade_hits
from repair_assistant.retrieval.strategies import _rrf


def test_grade_must_cite_and_must_not() -> None:
    fixture = {
        "must_cite": ["W11375982"],
        "must_not_cite": ["W11395614"],
    }
    ok, _, cited = grade_hits(
        fixture,
        [
            {"doc_id": "tsp-w11375982", "publication_number": "W11375982"},
            {"doc_id": "service-manual-w11169652", "publication_number": "W11169652"},
        ],
    )
    assert ok
    assert "W11375982" in cited

    bad, detail, _ = grade_hits(
        fixture,
        [{"doc_id": "tsp-w11395614", "publication_number": "W11395614"}],
    )
    assert not bad
    assert "must_not_cite" in detail


def test_rrf_prefers_shared_top_ranks() -> None:
    a = [
        {"doc_id": "d1", "chunk_id": "c1", "score": 0.9},
        {"doc_id": "d2", "chunk_id": "c2", "score": 0.8},
    ]
    b = [
        {"doc_id": "d2", "chunk_id": "c2", "score": 0.7},
        {"doc_id": "d1", "chunk_id": "c1", "score": 0.6},
    ]
    fused = _rrf([a, b])
    assert fused[0]["doc_id"] == "d1" or fused[0]["doc_id"] == "d2"
    assert len(fused) == 2
