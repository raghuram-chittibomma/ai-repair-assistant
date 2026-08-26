"""Eval-only synthetic documents for retrieval bake-off.

Kept under ``evals/retrieval/synthetic/``, never under ``corpus/``. Production
``search()`` excludes these hits; ``bench-retrieve`` upserts and grades them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from repair_assistant.corpus.manifest import Document, Manifest, _normalise_dates, repo_root
from repair_assistant.ingest.embeddings import Embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.parsed import ParsedChunk, ParsedDocument
from repair_assistant.ingest.store import Database

SYNTH_DOC_PREFIX = "synth-"
SYNTH_PUB_PREFIX = "SYNTH-"


def synthetic_root(root: Path | None = None) -> Path:
    return (root or repo_root()) / "evals" / "retrieval" / "synthetic"


def is_synthetic_doc_id(doc_id: str) -> bool:
    return doc_id.startswith(SYNTH_DOC_PREFIX)


def is_synthetic_publication(publication_number: str | None) -> bool:
    return bool(publication_number) and str(publication_number).startswith(SYNTH_PUB_PREFIX)


def is_synthetic_hit(hit: dict) -> bool:
    return is_synthetic_doc_id(str(hit.get("doc_id") or "")) or is_synthetic_publication(
        hit.get("publication_number")
    )


def load_synthetic_documents(root: Path | None = None) -> list[Document]:
    manifest_dir = synthetic_root(root) / "manifest"
    if not manifest_dir.is_dir():
        return []
    docs: list[Document] = []
    for path in sorted(manifest_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not data:
            continue
        doc = Document(data=_normalise_dates(data), path=path)
        if not is_synthetic_doc_id(doc.doc_id):
            raise ValueError(f"synthetic manifest {path.name}: doc_id must start with {SYNTH_DOC_PREFIX!r}")
        pub = doc.publication_number
        if pub and not is_synthetic_publication(pub):
            raise ValueError(
                f"synthetic manifest {path.name}: publication_number must start with {SYNTH_PUB_PREFIX!r}"
            )
        if (doc.data.get("corpus") or {}).get("role") != "synthetic_eval":
            raise ValueError(f"synthetic manifest {path.name}: corpus.role must be synthetic_eval")
        docs.append(doc)
    return docs


def merge_manifest_with_synthetic(corpus: Manifest, root: Path | None = None) -> Manifest:
    """Production corpus plus synthetic eval manifests (bake-off only)."""
    synth = load_synthetic_documents(root or corpus.root)
    if not synth:
        return corpus
    return Manifest(
        documents=list(corpus.documents) + synth,
        excluded=list(corpus.excluded),
        root=corpus.root,
    )


def _hash_text(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _parsed_from_manifest(doc: Document, root: Path) -> ParsedDocument:
    filename = (doc.data.get("provenance") or {}).get("local_filename")
    if not filename:
        raise ValueError(f"{doc.doc_id}: missing provenance.local_filename")
    path = synthetic_root(root) / "documents" / filename
    text = path.read_text(encoding="utf-8").replace("\x00", "").strip()
    if not text:
        raise ValueError(f"{path}: empty synthetic document")
    chunk = ParsedChunk(
        chunk_id="p1-prose-synth",
        text=text,
        page=1,
        kind="prose",
        error_codes=[],
        language="en-US",
        doc_id=doc.doc_id,
        publication_number=doc.publication_number,
        revision=doc.revision,
        metadata={"synthetic": True, "source": "evals/retrieval/synthetic"},
        content_hash=_hash_text(text),
    )
    meta = {
        "publication_number": doc.publication_number,
        "revision": doc.revision,
        "source": f"synthetic:{filename}",
        "extractor": "synthetic-eval",
        "synthetic": True,
        "title": doc.title,
        "doc_type": doc.doc_type,
    }
    return ParsedDocument(doc_id=doc.doc_id, path=path, meta=meta, chunks=[chunk])


def ensure_synthetic_ingested(
    db: Database,
    embedder: Embedder,
    *,
    root: Path | None = None,
) -> list[str]:
    """Upsert synthetic docs + embeddings. Returns doc_ids touched."""
    root = root or repo_root()
    touched: list[str] = []
    model = embedding_model()
    for doc in load_synthetic_documents(root):
        parsed = _parsed_from_manifest(doc, root)
        existing = db.get_document(doc.doc_id)
        keep: set[str] = set()
        if existing and existing.content_fingerprint == parsed.content_fingerprint:
            missing = db.chunks_missing_embeddings(doc.doc_id)
            if not missing:
                continue
            keep = {c.chunk_id for c in parsed.chunks}
        db.upsert_document(parsed, corpus_sha256=None)
        db.replace_chunks(doc.doc_id, parsed.chunks, keep_embeddings_for=keep)
        need = db.chunks_missing_embeddings(doc.doc_id)
        if need:
            vectors = embedder.embed([text for _, text in need])
            db.set_embeddings(
                doc.doc_id,
                [(cid, vec) for (cid, _), vec in zip(need, vectors, strict=True)],
                model,
            )
        db.commit()
        touched.append(doc.doc_id)
    return touched
