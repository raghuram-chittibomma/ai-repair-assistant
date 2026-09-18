"""Unit tests for the pre-LLM weak-evidence gate (ADR-0052)."""

from __future__ import annotations

from repair_assistant.corpus.support import (
    ABSTAIN_WEAK_EVIDENCE,
    WEAK_EVIDENCE_REASON,
    weak_evidence_message,
)
from repair_assistant.diagnostic.graph import should_reuse_session_evidence
from repair_assistant.qa.env import weak_evidence_min_score
from repair_assistant.retrieval.search import Hit
from repair_assistant.retrieval.weak_evidence import (
    assess_weak_evidence_pack,
    is_high_precision_hit,
    is_weak_evidence_pack,
)


def _hit(**kwargs) -> Hit:
    base = dict(
        doc_id="doc-a",
        chunk_id="c1",
        text="Generic procedure text about the washer.",
        page=1,
        kind="prose",
        error_codes=[],
        publication_number="W11169652",
        revision="A",
        score=0.40,
    )
    base.update(kwargs)
    return Hit(**base)


def test_gate_off_when_threshold_unset(monkeypatch) -> None:
    monkeypatch.delenv("REPAIR_WEAK_EVIDENCE_MIN_SCORE", raising=False)
    assert weak_evidence_min_score() is None
    assert not is_weak_evidence_pack([_hit(score=0.1)], query="noise", min_score=None)


def test_gate_off_when_threshold_zero(monkeypatch) -> None:
    monkeypatch.setenv("REPAIR_WEAK_EVIDENCE_MIN_SCORE", "0")
    assert weak_evidence_min_score() is None


def test_weak_vector_only_pack_abstains() -> None:
    hits = [_hit(score=0.42), _hit(chunk_id="c2", score=0.38)]
    assessment = assess_weak_evidence_pack(hits, query="why is my toaster humming", min_score=0.55)
    assert assessment.weak
    assert assessment.top_score == 0.42
    assert not assessment.precision_exempt
    assert assessment.as_trace_dict()["weak_evidence_gate"] == "abstain"


def test_strong_vector_pack_passes() -> None:
    hits = [_hit(score=0.81)]
    assert not is_weak_evidence_pack(hits, query="door won't unlock", min_score=0.55)


def test_exact_arm_sentinel_exempts() -> None:
    hits = [_hit(score=1.0, error_codes=["F5E2"], text="F5E2 door lock fault")]
    assessment = assess_weak_evidence_pack(hits, query="random fluff", min_score=0.90)
    assert not assessment.weak
    assert assessment.precision_exempt


def test_code_overlap_exempts_even_with_low_score() -> None:
    hits = [_hit(score=0.20, error_codes=["F5E2"], text="Door lock F5E2 table")]
    assert is_high_precision_hit(hits[0], "washer shows F5E2")
    assert not is_weak_evidence_pack(hits, query="washer shows F5E2", min_score=0.55)


def test_connector_overlap_exempts() -> None:
    hits = [_hit(score=0.30, text="Pin J36 on the ACU harness")]
    assert not is_weak_evidence_pack(hits, query="what is connector J36", min_score=0.55)


def test_named_publication_exempts() -> None:
    hits = [_hit(score=0.30, publication_number="W11320651")]
    assert not is_weak_evidence_pack(
        hits, query="shipping bolts in W11320651", min_score=0.55
    )


def test_empty_hits_not_weak() -> None:
    """Empty packs are ABSTAIN_NO_EVIDENCE at the caller, not this gate."""
    assert not is_weak_evidence_pack([], query="anything", min_score=0.55)


def test_progress_reuse_skips_search_path() -> None:
    """Gate is only wired on search; reuse must remain true for ack + pack."""
    assert should_reuse_session_evidence(
        label="ack",
        latest="ok done",
        has_pack=True,
    )
    assert not should_reuse_session_evidence(
        label="new_symptom",
        latest="now the door won't open",
        has_pack=True,
    )


def test_weak_evidence_message_and_code() -> None:
    assert ABSTAIN_WEAK_EVIDENCE == "weak_evidence"
    assert "sufficiently matching" in weak_evidence_message(None).lower()
    assert "Documentation set" in WEAK_EVIDENCE_REASON
