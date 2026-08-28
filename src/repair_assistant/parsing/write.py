"""Write structured chunks to corpus/parsed/."""

from __future__ import annotations

import json
from pathlib import Path

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.parsing.chunk_quality import audit_and_improve
from repair_assistant.parsing.chunker import chunk_document
from repair_assistant.parsing.extractors import get_extractor
from repair_assistant.parsing.mhtml import html_to_visible_text, load_mhtml
from repair_assistant.parsing.models import Chunk

# Default production path (ADR-0024 hybrid router). Overridable via CLI.
DEFAULT_EXTRACTOR = "hybrid"


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

    extracted = None
    quality = None
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
            doc_title=document.title,
            doc_type=document.doc_type,
            strategy="structured",
        )
        chunks, quality = audit_and_improve(chunks)

    with dest.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")

    meta = {
        "doc_id": document.doc_id,
        "extractor": extractor_name if source.suffix.lower() == ".pdf" else "mhtml",
        "chunk_count": len(chunks),
        "source": document.local_filename,
    }
    if quality is not None:
        meta["quality_stop_reason"] = quality.stop_reason
        meta["quality_critical_count"] = sum(
            1 for f in quality.findings if f.severity == "critical"
        )
        (dest_dir / "chunk_quality.json").write_text(
            json.dumps({"doc_id": document.doc_id, **quality.to_json()}, indent=2) + "\n",
            encoding="utf-8",
        )
    if source.suffix.lower() == ".pdf" and extracted and extracted.parse_audit:
        (dest_dir / "parse_audit.json").write_text(
            json.dumps(extracted.parse_audit, indent=2) + "\n",
            encoding="utf-8",
        )
        meta["parse_audit_pages"] = len(extracted.parse_audit.get("page_audits", []))
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return dest


def _chunks_from_mhtml(path: Path, document: manifest_mod.Document) -> list[Chunk]:
    import re

    from repair_assistant.parsing.error_codes import extract_error_codes

    html = load_mhtml(path)
    text = html_to_visible_text(html)
    # Prefer the slug (kb-f5e2-…) and lead copy — full MindTouch pages list many
    # sibling codes in nav chrome, which poisons specificity ranking.
    slug_codes = [
        f"F{a}E{b}".upper()
        for a, b in re.findall(r"f(\d)e(\d)", document.doc_id, flags=re.IGNORECASE)
    ]
    lead_codes = extract_error_codes(text[:1200])
    codes = list(dict.fromkeys([*slug_codes, *lead_codes]))
    if not codes:
        codes = extract_error_codes(text)
    if codes:
        text = "Error codes: " + ", ".join(codes) + "\n\n" + text
    return [
        Chunk(
            chunk_id=f"{document.doc_id}-article",
            text=text,
            page=1,
            kind="article",
            error_codes=codes,
            language="en",
            doc_id=document.doc_id,
            publication_number=document.publication_number,
            revision=document.revision,
            metadata={"source": "mhtml"},
        )
    ]
