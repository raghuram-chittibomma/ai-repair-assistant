"""Read corpus/parsed/<doc_id>/ artefacts produced by Phase 2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from repair_assistant.parsing.pua import strip_nul_chars


@dataclass(frozen=True)
class ParsedChunk:
    chunk_id: str
    text: str
    page: int | None
    kind: str | None
    error_codes: list[str]
    language: str | None
    doc_id: str
    publication_number: str | None
    revision: str | None
    metadata: dict[str, Any]
    content_hash: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ParsedChunk:
        # Postgres rejects NUL (0x00) in text and jsonb; PDF extractors
        # occasionally emit them (e.g. "Action" → "Ac\\u0000on").
        raw_text = str(data["text"])
        text = strip_nul_chars(raw_text)
        metadata = strip_nul_chars(dict(data.get("metadata") or {}))
        had_nul = raw_text != text or metadata != dict(data.get("metadata") or {})
        content_hash = (
            _hash_text(text)
            if had_nul or not data.get("content_hash")
            else str(data["content_hash"])
        )
        return cls(
            chunk_id=data["chunk_id"],
            text=text,
            page=data.get("page"),
            kind=data.get("kind"),
            error_codes=list(data.get("error_codes") or []),
            language=data.get("language"),
            doc_id=data["doc_id"],
            publication_number=data.get("publication_number"),
            revision=data.get("revision"),
            metadata=metadata,
            content_hash=content_hash,
        )


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    path: Path
    meta: dict[str, Any]
    chunks: list[ParsedChunk]

    @property
    def content_fingerprint(self) -> str:
        """Stable digest of the chunk set for skip-if-unchanged ingest."""
        material = "\n".join(
            f"{c.chunk_id}:{c.content_hash}" for c in sorted(self.chunks, key=lambda x: x.chunk_id)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def parsed_root(corpus_root: Path) -> Path:
    return corpus_root / "parsed"


def iter_parsed_dirs(corpus_root: Path) -> Iterator[Path]:
    root = parsed_root(corpus_root)
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "chunks.jsonl").is_file():
            yield child


def load_parsed_document(doc_dir: Path) -> ParsedDocument:
    meta_path = doc_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    chunks: list[ParsedChunk] = []
    with (doc_dir / "chunks.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            chunks.append(ParsedChunk.from_json(json.loads(line)))

    doc_id = meta.get("doc_id") or doc_dir.name
    if chunks and any(c.doc_id != doc_id for c in chunks):
        # Prefer directory / meta as source of truth; chunks should already match.
        doc_id = chunks[0].doc_id
    return ParsedDocument(doc_id=doc_id, path=doc_dir, meta=meta, chunks=chunks)
