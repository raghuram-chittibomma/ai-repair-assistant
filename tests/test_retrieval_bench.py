"""Unit tests for retrieval grading helpers (no Postgres)."""

from __future__ import annotations

from repair_assistant.retrieval.bench import compute_ir_metrics, grade_hits
from repair_assistant.retrieval.strategies import _rrf, _union_pool, query_literals


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


def test_rrf_collapses_scores_below_boost_scale() -> None:
    """Why RRF hybrid lets boosts dominate: fused scores are ~1/60, boosts are 0.02-0.35."""
    fused = _rrf([[{"doc_id": "d1", "chunk_id": "c1", "score": 0.87}]])
    assert fused[0]["score"] < 0.02


def test_union_pool_preserves_vector_magnitude() -> None:
    vector = [
        {"doc_id": "d1", "chunk_id": "c1", "score": 0.90},
        {"doc_id": "d2", "chunk_id": "c2", "score": 0.70},
    ]
    aux = [
        {"doc_id": "d3", "chunk_id": "c3", "score": 0.5},
        {"doc_id": "d4", "chunk_id": "c4", "score": 0.1},
    ]
    pool = _union_pool(vector, aux)
    by_key = {h["chunk_id"]: h for h in pool}

    assert by_key["c1"]["score"] == 0.90
    assert by_key["c2"]["score"] == 0.70
    # Auxiliary hits land inside the observed vector band, top-ranked at vmax.
    assert by_key["c3"]["score"] == 0.90
    assert 0.70 <= by_key["c4"]["score"] < 0.90


def test_union_pool_keeps_better_score_on_agreement() -> None:
    vector = [{"doc_id": "d1", "chunk_id": "c1", "score": 0.60}]
    aux = [{"doc_id": "d1", "chunk_id": "c1", "score": 0.95}]
    pool = _union_pool(vector, aux)
    assert len(pool) == 1
    assert pool[0]["score"] == 0.60


def test_union_pool_without_aux_is_identity() -> None:
    vector = [{"doc_id": "d1", "chunk_id": "c1", "score": 0.42}]
    assert _union_pool(vector, [])[0]["score"] == 0.42


def test_query_literals_extracts_mixed_alphanumerics() -> None:
    assert query_literals("Is part number W10804741 the door lock?") == ["W10804741"]
    assert query_literals("What connects to J36 on the ACU?") == ["J36"]
    assert query_literals("F5E2 on a WFW5620HW0") == ["F5E2", "WFW5620HW0"]


def test_query_literals_skips_pure_words_and_numbers() -> None:
    assert query_literals("my washer shakes during the spin cycle") == []
    assert query_literals("check pin 3 and pin 12") == []
