"""Write structured chunks to corpus/parsed/."""

from __future__ import annotations

import json
from pathlib import Path

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.parsing.chunker import chunk_document
from repair_assistant.parsing.extractors import get_extractor
from repair_assistant.parsing.mhtml import html_to_visible_text, load_mhtml
from repair_assistant.parsing.models import Chunk

# Default winner from the Phase 2 bake-off (see ADR-0007). Overridable via CLI.
DEFAULT_EXTRACTOR = "pdfplumber"


def parsed_dir(root: Path | None = None) -> Path:
    root = root or manifest_mod.load().root
    return root / "corpus" / "parsed"


def parse_document(
    document: manifest_mod.Document,
    *,
    extractor_name: str = DEFAULT_EXTRACTOR,
    documents_dir: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Extract, chunk, and write JSONL for one manifest document. Returns out path."""
    corpus = manifest_mod.load()
    documents_dir = documents_dir or corpus.documents_dir
    out_root = out_dir or parsed_dir(corpus.root)
    source = documents_dir / document.local_filename
    if not source.is_file():
        raise FileNotFoundError(source)

    dest_dir = out_root / document.doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "chunks.jsonl"

    if source.suffix.lower() in {".mhtml", ".mht", ".html", ".htm"}:
        chunks = _chunks_from_mhtml(source, document)
    else:
        extractor = get_extractor(extractor_name)
        extracted = extractor.extract(source)
        chunks = chunk_document(
            extracted,
            doc_id=document.doc_id,
            publication_number=document.publication_number,
            revision=document.revision,
            strategy="structured",
        )

    with dest.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")

    meta = {
        "doc_id": document.doc_id,
        "extractor": extractor_name if source.suffix.lower() == ".pdf" else "mhtml",
        "chunk_count": len(chunks),
        "source": document.local_filename,
    }
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return dest


def _chunks_from_mhtml(path: Path, document: manifest_mod.Document) -> list[Chunk]:
    html = load_mhtml(path)
    text = html_to_visible_text(html)
    return [
        Chunk(
            chunk_id=f"{document.doc_id}-article",
            text=text,
            page=1,
            kind="article",
            error_codes=[],
            language="en",
            doc_id=document.doc_id,
            publication_number=document.publication_number,
            revision=document.revision,
            metadata={"source": "mhtml"},
        )
    ]
