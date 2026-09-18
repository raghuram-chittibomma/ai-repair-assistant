"""REPAIR_EVIDENCE_MAX_CHARS — generate evidence pack budget."""

from __future__ import annotations

import pytest

from repair_assistant.qa import env as qa_env
from repair_assistant.qa.context import format_evidence
from repair_assistant.retrieval.search import Hit


def _hit(*, chunk_id: str, text: str, **kwargs) -> Hit:
    defaults = {
        "doc_id": "doc-a",
        "chunk_id": chunk_id,
        "text": text,
        "page": 1,
        "kind": "prose",
        "error_codes": [],
        "publication_number": "PUB",
        "revision": "A",
        "score": 0.9,
    }
    defaults.update(kwargs)
    return Hit(**defaults)


def test_evidence_max_chars_unset_means_unlimited(monkeypatch) -> None:
    monkeypatch.delenv("REPAIR_EVIDENCE_MAX_CHARS", raising=False)
    assert qa_env.evidence_max_chars() is None


def test_evidence_max_chars_zero_means_unlimited(monkeypatch) -> None:
    monkeypatch.setenv("REPAIR_EVIDENCE_MAX_CHARS", "0")
    assert qa_env.evidence_max_chars() is None


def test_evidence_max_chars_positive(monkeypatch) -> None:
    monkeypatch.setenv("REPAIR_EVIDENCE_MAX_CHARS", "12000")
    assert qa_env.evidence_max_chars() == 12_000


def test_evidence_max_chars_rejects_negative(monkeypatch) -> None:
    monkeypatch.setenv("REPAIR_EVIDENCE_MAX_CHARS", "-1")
    with pytest.raises(RuntimeError, match="REPAIR_EVIDENCE_MAX_CHARS"):
        qa_env.evidence_max_chars()


def test_format_evidence_honours_env_budget(monkeypatch) -> None:
    # Labels include the [structured]/[semantic] tag and modality lines
    # (ADR-0050/0051), so the budget must leave room for that overhead after
    # the mandatory top hit.
    monkeypatch.setenv("REPAIR_EVIDENCE_MAX_CHARS", "180")
    big = _hit(chunk_id="a", text="A" * 40)
    small = _hit(chunk_id="b", text="B" * 80)
    tiny = _hit(chunk_id="c", text="ok")
    _, citations = format_evidence([big, small, tiny])
    assert [c.chunk_id for c in citations] == ["a", "c"]


def test_format_evidence_unlimited_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("REPAIR_EVIDENCE_MAX_CHARS", raising=False)
    hits = [_hit(chunk_id=f"h{i}", text="X" * 3_000) for i in range(4)]
    _, citations = format_evidence(hits)
    assert len(citations) == 4
