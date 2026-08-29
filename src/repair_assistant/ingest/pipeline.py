"""Incremental ingest of parsed JSONL into Postgres."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repair_assistant.ingest.embeddings import (
    Embedder,
    assert_embedding_model,
    clear_embeddings_for_other_models,
)
from repair_assistant.ingest.parsed import (
    ParsedDocument,
    iter_parsed_dirs,
    load_parsed_document,
)
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.language import is_index_language
from repair_assistant.parsing.page_classify import should_index_chunk


@dataclass
class DocIngestStats:
    doc_id: str
    status: str  # skipped | upserted | failed
    chunks: int = 0
    embedded: int = 0
    detail: str = ""


@dataclass
class IngestResult:
    documents: list[DocIngestStats] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return sum(1 for d in self.documents if d.status == "skipped")

    @property
    def upserted(self) -> int:
        return sum(1 for d in self.documents if d.status == "upserted")

    @property
    def failed(self) -> int:
        return sum(1 for d in self.documents if d.status == "failed")


def ingest_parsed(
    db: Database,
    corpus_root: Path,
    embedder: Embedder,
    *,
    doc_ids: set[str] | None = None,
    force: bool = False,
    corpus_sha_by_doc: dict[str, str] | None = None,
) -> IngestResult:
    """Load corpus/parsed into the database, skipping unchanged fingerprints."""
    result = IngestResult()
    corpus_sha_by_doc = corpus_sha_by_doc or {}
    if embedder.model != "none":
        if force:
            clear_embeddings_for_other_models(db, embedder.model)
        else:
            assert_embedding_model(db, embedder.model)

    targets: list[Path] = []
    for path in iter_parsed_dirs(corpus_root):
        if doc_ids is None or path.name in doc_ids:
            targets.append(path)

    if doc_ids is not None:
        found = {p.name for p in targets}
        for missing in sorted(doc_ids - found):
            result.documents.append(
                DocIngestStats(doc_id=missing, status="failed", detail="no corpus/parsed dir")
            )

    for path in targets:
        try:
            parsed = load_parsed_document(path)
            stats = _ingest_one(
                db,
                parsed,
                embedder,
                force=force,
                corpus_sha256=corpus_sha_by_doc.get(parsed.doc_id),
            )
            result.documents.append(stats)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — surface per-doc failures to CLI
            db._conn.rollback()
            result.documents.append(
                DocIngestStats(doc_id=path.name, status="failed", detail=str(exc))
            )
    return result


def _ingest_one(
    db: Database,
    parsed: ParsedDocument,
    embedder: Embedder,
    *,
    force: bool,
    corpus_sha256: str | None,
) -> DocIngestStats:
    existing = db.get_document(parsed.doc_id)
    if (
        not force
        and existing
        and existing.content_fingerprint == parsed.content_fingerprint
    ):
        # Still fill any NULL embeddings (e.g. prior --skip-embed run).
        embedded = _embed_missing(db, parsed.doc_id, embedder)
        if embedded:
            return DocIngestStats(
                doc_id=parsed.doc_id,
                status="upserted",
                chunks=len(parsed.chunks),
                embedded=embedded,
                detail="fingerprint unchanged; filled missing embeddings",
            )
        return DocIngestStats(
            doc_id=parsed.doc_id,
            status="skipped",
            chunks=len(parsed.chunks),
            detail="content fingerprint unchanged",
        )

    indexable = [
        c
        for c in parsed.chunks
        if should_index_chunk(c.text, c.kind) and is_index_language(c.language)
    ]
    prior_hashes = db.existing_chunk_hashes(parsed.doc_id)
    keep = {
        c.chunk_id
        for c in indexable
        if prior_hashes.get(c.chunk_id) == c.content_hash
    }

    db.upsert_document(parsed, corpus_sha256)
    db.replace_chunks(parsed.doc_id, indexable, keep_embeddings_for=keep)
    embedded = _embed_missing(db, parsed.doc_id, embedder)
    return DocIngestStats(
        doc_id=parsed.doc_id,
        status="upserted",
        chunks=len(parsed.chunks),
        embedded=embedded,
    )


def _embed_missing(db: Database, doc_id: str, embedder: Embedder) -> int:
    missing = [
        m
        for m in db.chunks_missing_embeddings(doc_id)
        if should_index_chunk(m[1], None)
    ]
    if not missing:
        return 0
    if embedder.model == "none":
        return 0
    ids = [m[0] for m in missing]
    texts = [m[1] for m in missing]
    vectors = embedder.embed(texts)
    db.set_embeddings(doc_id, list(zip(ids, vectors, strict=True)), embedder.model)
    return len(ids)
