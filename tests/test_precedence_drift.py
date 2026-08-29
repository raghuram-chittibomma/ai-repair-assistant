"""Manifest-only precedence drift checks (review R19)."""

from __future__ import annotations

from pathlib import Path

from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.corpus.precedence_drift import drift_notices, newer_revision_note
from repair_assistant.retrieval.search import Hit


def _doc(
    doc_id: str,
    pub: str,
    *,
    revision: str | None = None,
    date: str | None = None,
    title: str = "Doc",
    relationships: list | None = None,
) -> Document:
    data = {
        "doc_id": doc_id,
        "title": title,
        "doc_type": "service_manual",
        "corpus": {"role": "primary"},
        "publication_number": pub,
        "revision": revision,
        "temporal": {"publication_date": date} if date else {},
        "relationships": relationships or [],
    }
    return Document(data=data, path=Path(f"{doc_id}.yaml"))


def test_unlinked_revisions_are_flagged() -> None:
    manifest = Manifest(
        documents=[
            _doc("old", "W111", revision="A", date="2019-01"),
            _doc("new", "W111", revision="B", date="2019-06"),
        ]
    )
    notices = drift_notices(manifest)
    assert any("multiple editions" in n for n in notices)


def test_supersedes_edge_clears_revision_flag() -> None:
    manifest = Manifest(
        documents=[
            _doc("old", "W111", revision="A", date="2019-01"),
            _doc(
                "new",
                "W111",
                revision="B",
                date="2019-06",
                relationships=[{"type": "supersedes", "target": "W111"}],
            ),
        ]
    )
    assert not any("multiple editions" in n for n in drift_notices(manifest))


def test_newer_doc_naming_older_without_edge() -> None:
    manifest = Manifest(
        documents=[
            _doc("manual", "W11169652", revision="A", date="2019-05"),
            _doc(
                "tsp",
                "W11375982",
                date="2019-06",
                title="Correction for W11169652 ACU LED",
            ),
        ]
    )
    notices = drift_notices(manifest)
    assert any("W11169652" in n and "no precedence edge" in n for n in notices)


def test_newer_revision_note_on_stale_hit() -> None:
    manifest = Manifest(
        documents=[
            _doc("old", "W111", revision="A", date="2019-01"),
            _doc("new", "W111", revision="B", date="2019-06"),
        ]
    )
    hit = Hit(
        doc_id="old",
        chunk_id="p1",
        text="Step 10",
        page=1,
        kind="prose",
        error_codes=[],
        publication_number="W111",
        revision="A",
        score=0.5,
    )
    note = newer_revision_note([hit], manifest)
    assert note is not None
    assert "Rev B" in note
