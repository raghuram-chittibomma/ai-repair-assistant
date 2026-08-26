"""Unit tests for retrieval grading helpers (no Postgres)."""

from __future__ import annotations

from repair_assistant.retrieval.bench import compute_ir_metrics, grade_hits
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


def test_ir_recall_precision_hit_at_k() -> None:
    fixture = {
        "must_cite": ["W11375982"],
        "must_not_cite": ["W11395614"],
    }
    hits = [
        {"doc_id": "tsp-w11375982", "publication_number": "W11375982"},
        {"doc_id": "service-manual-w11169652", "publication_number": "W11169652"},
        {"doc_id": "tech-sheet-w11320651", "publication_number": "W11320651"},
    ]
    m = compute_ir_metrics(fixture, hits, k=8)
    assert m.hit_at_k is True
    assert m.recall_at_k == 1.0
    assert m.precision_at_k == 1 / 3
    assert m.forbidden_in_top_k == 0

    miss = compute_ir_metrics(
        fixture,
        [{"doc_id": "service-manual-w11169652", "publication_number": "W11169652"}],
        k=8,
    )
    assert miss.hit_at_k is False
    assert miss.recall_at_k == 0.0
    assert miss.precision_at_k == 0.0


def test_ir_must_cite_any_counts_as_one_target() -> None:
    fixture = {"must_cite_any": ["W11320651", "W11156989"]}
    hits = [
        {"doc_id": "tech-sheet-w11156989-revd", "publication_number": "W11156989"},
        {"doc_id": "other", "publication_number": "X"},
    ]
    m = compute_ir_metrics(fixture, hits, k=8)
    assert m.hit_at_k is True
    assert m.relevant_total == 1
    assert m.recall_at_k == 1.0
    assert m.precision_at_k == 0.5


def test_ir_forbidden_only_fixture() -> None:
    fixture = {"must_not_cite": ["W11395614"]}
    m = compute_ir_metrics(
        fixture,
        [{"doc_id": "service-manual-w11169652", "publication_number": "W11169652"}],
        k=8,
    )
    assert m.hit_at_k is None
    assert m.recall_at_k is None
    assert m.precision_at_k is None
    assert m.forbidden_in_top_k == 0

    contaminated = compute_ir_metrics(
        fixture,
        [{"doc_id": "tsp-w11395614", "publication_number": "W11395614"}],
        k=8,
    )
    assert contaminated.forbidden_in_top_k == 1


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
