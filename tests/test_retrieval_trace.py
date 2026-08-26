"""Tests for retrieval trace serialization."""

from __future__ import annotations

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.observability.retrieval_trace import build_retrieval_trace_output
from repair_assistant.retrieval.rank import RankAudit, RankedHit
from repair_assistant.retrieval.search import Hit


def test_build_retrieval_trace_output_includes_audit_sections() -> None:
    audit = RankAudit(
        rejected=[
            {
                "doc_id": "wrong-doc",
                "chunk_id": "p1",
                "apply_reason": "model mismatch",
            }
        ],
        ranked_sorted=[
            RankedHit(
                doc_id="tech-sheet-w11320651",
                chunk_id="p1",
                text="F5E2 door lock",
                page=1,
                kind="table_row",
                error_codes=["F5E2"],
                publication_number="W11320651",
                revision="B",
                score=0.8,
                applies=True,
                apply_reason="ok",
                authority_boost=0.1,
            )
        ],
        diversity_dropped=[
            {
                "doc_id": "tech-sheet-w11320651",
                "chunk_id": "p2",
                "reason": "max_per_doc=2",
            }
        ],
    )
    hits = [
        Hit(
            doc_id="tech-sheet-w11320651",
            chunk_id="p1",
            text="F5E2 door lock",
            page=1,
            kind="table_row",
            error_codes=["F5E2"],
            publication_number="W11320651",
            revision="B",
            score=0.9,
            apply_reason="ok",
        )
    ]
    out = build_retrieval_trace_output(
        query="F5E2",
        appliance=Appliance(model="WFW5620HW0"),
        limit=8,
        overfetch=40,
        source_counts={"vector": 40, "code": 1, "connector": 0, "reference": 0, "revision": 0},
        merged_count=41,
        audit=audit,
        final_hits=hits,
        bibliographic=False,
        revision_query=None,
    )
    assert out["selected_count"] == 1
    assert out["rejected_applicability"][0]["doc_id"] == "wrong-doc"
    assert out["ranked_before_diversity"][0]["doc_id"] == "tech-sheet-w11320651"
    assert out["diversity_dropped"][0]["reason"] == "max_per_doc=2"
