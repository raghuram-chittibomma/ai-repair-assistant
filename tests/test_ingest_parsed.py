"""Unit tests for Phase 3 parsed-load and fingerprinting (no Postgres required)."""

from __future__ import annotations

import json
from pathlib import Path

from repair_assistant.ingest.embeddings import NullEmbedder, build_embedder
from repair_assistant.ingest.parsed import ParsedChunk, load_parsed_document


def _write_parsed(tmp: Path, doc_id: str, chunks: list[dict]) -> Path:
    doc_dir = tmp / doc_id
    doc_dir.mkdir(parents=True)
    (doc_dir / "meta.json").write_text(
        json.dumps({"doc_id": doc_id, "extractor": "pdfplumber", "chunk_count": len(chunks)}),
        encoding="utf-8",
    )
    with (doc_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for row in chunks:
            fh.write(json.dumps(row) + "\n")
    return doc_dir


def test_load_parsed_and_fingerprint_stable(tmp_path: Path) -> None:
    rows = [
        {
            "chunk_id": "b",
            "text": "Door lock  F5E1",
            "page": 2,
            "kind": "table_row",
            "error_codes": ["F5E1"],
            "language": "en",
            "doc_id": "doc-a",
            "publication_number": "W11320651",
            "revision": "B",
            "metadata": {},
        },
        {
            "chunk_id": "a",
            "text": "Safety first",
            "page": 1,
            "kind": "procedure",
            "error_codes": [],
            "language": "en",
            "doc_id": "doc-a",
            "publication_number": "W11320651",
            "revision": "B",
            "metadata": {},
        },
    ]
    doc = load_parsed_document(_write_parsed(tmp_path, "doc-a", rows))
    assert doc.doc_id == "doc-a"
    assert len(doc.chunks) == 2
    assert all(isinstance(c, ParsedChunk) for c in doc.chunks)
    fp1 = doc.content_fingerprint
    # Reorder on disk should not matter — fingerprint sorts by chunk_id.
    rows_rev = list(reversed(rows))
    doc2 = load_parsed_document(_write_parsed(tmp_path / "other", "doc-a", rows_rev))
    assert doc2.content_fingerprint == fp1


def test_fingerprint_changes_when_text_changes(tmp_path: Path) -> None:
    base = {
        "chunk_id": "a",
        "text": "alpha",
        "page": 1,
        "kind": "prose",
        "error_codes": [],
        "language": "en",
        "doc_id": "d",
        "publication_number": None,
        "revision": None,
        "metadata": {},
    }
    d1 = load_parsed_document(_write_parsed(tmp_path, "d", [base]))
    changed = {**base, "text": "beta"}
    d2 = load_parsed_document(_write_parsed(tmp_path / "x", "d", [changed]))
    assert d1.content_fingerprint != d2.content_fingerprint


def test_build_embedder_skip() -> None:
    null = build_embedder(skip=True, model="BAAI/bge-base-en-v1.5")
    assert isinstance(null, NullEmbedder)
    assert null.embed(["hi"]) == [[]]
