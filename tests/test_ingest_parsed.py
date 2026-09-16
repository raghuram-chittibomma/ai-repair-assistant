"""Unit tests for Phase 3 parsed-load and fingerprinting (no Postgres required)."""

from __future__ import annotations

import json
from pathlib import Path

from repair_assistant.ingest.embeddings import NullEmbedder, build_embedder
from repair_assistant.ingest.parsed import ParsedChunk, load_parsed_document
from repair_assistant.parsing.pua import strip_nul_chars


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


def test_load_parsed_strips_nul_from_text_and_metadata(tmp_path: Path) -> None:
    row = {
        "chunk_id": "a",
        "text": "Ac\u0000on Required",
        "page": 1,
        "kind": "prose",
        "error_codes": [],
        "language": "en",
        "doc_id": "tsp-w11533288",
        "publication_number": "W11533288",
        "revision": None,
        "metadata": {"body_text": "Informa\u0000on Only"},
        "content_hash": "stale-hash-with-nuls",
    }
    doc = load_parsed_document(_write_parsed(tmp_path, "tsp-w11533288", [row]))
    assert "\x00" not in doc.chunks[0].text
    assert doc.chunks[0].text == "Acon Required"
    assert doc.chunks[0].metadata["body_text"] == "Informaon Only"
    assert "\x00" not in json.dumps(doc.chunks[0].metadata)
    # Hash recomputed from cleaned text (not the stale on-disk hash).
    assert doc.chunks[0].content_hash != "stale-hash-with-nuls"


def test_ingest_updates_metadata_when_fingerprint_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from unittest.mock import MagicMock

    from repair_assistant.ingest import pipeline as pipeline_mod
    from repair_assistant.ingest.pipeline import _ingest_one
    from repair_assistant.ingest.store import DocumentRow
    from repair_assistant.semantic.lifecycle import (
        STATUS_ACTIVE,
        STRATEGY_STRUCTURED,
        IngestionVersion,
    )

    monkeypatch.setattr(
        pipeline_mod,
        "ensure_structured_active",
        lambda db, doc_id, *, source_fingerprint: IngestionVersion(
            id=1,
            doc_id=doc_id,
            version=1,
            strategy=STRATEGY_STRUCTURED,
            status=STATUS_ACTIVE,
        ),
    )

    base = {
        "chunk_id": "a",
        "text": "F5E2 door lock",
        "page": 8,
        "kind": "table_row",
        "error_codes": ["F5E2"],
        "language": "en",
        "doc_id": "tech-sheet",
        "publication_number": "W11320651",
        "revision": "A",
        "metadata": {"bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4}, "page_width": 612},
    }
    parsed = load_parsed_document(_write_parsed(tmp_path, "tech-sheet", [base]))
    db = MagicMock()
    db.get_document.return_value = DocumentRow(
        doc_id=parsed.doc_id,
        content_fingerprint=parsed.content_fingerprint,
        chunk_count=1,
    )
    db.chunks_missing_embeddings.return_value = []
    db.update_chunk_metadata.return_value = 1
    stats = _ingest_one(db, parsed, NullEmbedder(), force=False, corpus_sha256=None)
    assert stats.status == "upserted"
    assert "metadata" in stats.detail
    db.update_chunk_metadata.assert_called_once()
    db.replace_chunks.assert_not_called()


def test_strip_nul_chars_recursive() -> None:
    assert strip_nul_chars("a\x00b") == "ab"
    assert strip_nul_chars({"x": "a\x00b", "y": ["c\x00"]}) == {"x": "ab", "y": ["c"]}
