"""Turn an ExtractedDocument into retrieval chunks.

Table rows that look like error-code entries become one chunk each with the
code in structured metadata. Prose falls back to heading-aware paragraphs —
never blank-line-only or fixed-size splits as the primary strategy.
"""

from __future__ import annotations

import hashlib
import re

from .models import Chunk, ExtractedDocument, Table
from .pua import map_pua, split_list_items

_ERROR_CODE_RE = re.compile(r"\b(F\dE\d)\b")
_HEADING_RE = re.compile(
    r"^(FOR SERVICE TECHNICIAN|DIAGNOSTIC|TEST #\d|ERROR CODE|IMPORTANT|"
    r"WARNING|ABBREVIATIONS|TECHNICAL SERVICE POINTER)",
    re.IGNORECASE,
)


def chunk_document(
    document: ExtractedDocument,
    *,
    doc_id: str | None = None,
    publication_number: str | None = None,
    revision: str | None = None,
    strategy: str = "structured",
) -> list[Chunk]:
    """Chunk ``document``.

    ``strategy``:
      - ``structured`` — table rows + heading/prose (production path)
      - ``naive_fixed`` — fixed-size windows on raw page text (baseline, expected to fail binding)
    """
    if strategy == "naive_fixed":
        return _naive_fixed_chunks(document, doc_id, publication_number, revision)
    return _structured_chunks(document, doc_id, publication_number, revision)


def _structured_chunks(
    document: ExtractedDocument,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in document.pages:
        for table in page.tables:
            chunks.extend(
                _chunks_from_table(
                    table,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    language=page.language,
                )
            )
        # Prose from blocks not already covered as tables.
        prose_text = map_pua(page.text)
        if page.tables and _looks_like_error_table(page.tables[0]):
            # Still keep non-table prose by removing table cell strings roughly.
            pass
        for piece in _split_prose(prose_text):
            codes = _ERROR_CODE_RE.findall(piece)
            kind = "heading" if _HEADING_RE.match(piece.strip()) else "prose"
            if "•" in piece and len(split_list_items(piece)) > 1:
                kind = "procedure"
            chunks.append(
                _make_chunk(
                    text=piece,
                    page=page.number,
                    kind=kind,
                    error_codes=list(dict.fromkeys(codes)),
                    language=page.language,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    extractor=document.extractor,
                )
            )
    return _dedupe_prefer_table_rows(chunks)


def _chunks_from_table(
    table: Table,
    *,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    language: str | None,
) -> list[Chunk]:
    headers = [h.lower() for h in table.headers]
    error_col = next((i for i, h in enumerate(headers) if "error" in h or "code" in h), 0)
    chunks: list[Chunk] = []
    for row in table.rows:
        cells = row.cells
        if not cells:
            continue
        code_cell = cells[error_col] if error_col < len(cells) else cells[0]
        codes = _ERROR_CODE_RE.findall(code_cell)
        # Also accept a bare F#E# as the whole first cell.
        if not codes and re.fullmatch(r"F\dE\d", code_cell.strip()):
            codes = [code_cell.strip()]
        text = " | ".join(c for c in cells if c)
        text = map_pua(text)
        if not text.strip():
            continue
        chunks.append(
            _make_chunk(
                text=text,
                page=table.page,
                kind="table_row",
                error_codes=list(dict.fromkeys(codes)),
                language=language,
                doc_id=doc_id,
                publication_number=publication_number,
                revision=revision,
                extractor=None,
                metadata={"headers": table.headers},
            )
        )
    return chunks


def _naive_fixed_chunks(
    document: ExtractedDocument,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    size: int = 200,
) -> list[Chunk]:
    """Control chunker: fixed windows that routinely split codes from remedies."""
    chunks: list[Chunk] = []
    for page in document.pages:
        text = page.text or ""
        for start in range(0, max(len(text), 1), size):
            window = text[start : start + size]
            if not window.strip():
                continue
            codes = _ERROR_CODE_RE.findall(window)
            chunks.append(
                _make_chunk(
                    text=window,
                    page=page.number,
                    kind="prose",
                    error_codes=list(dict.fromkeys(codes)),
                    language=page.language,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    extractor=document.extractor,
                    metadata={"strategy": "naive_fixed", "size": size},
                )
            )
    return chunks


def _split_prose(text: str) -> list[str]:
    if not text.strip():
        return []
    # Split on heading-like lines while keeping the heading with following body
    # until the next heading.
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if _HEADING_RE.match(line.strip()) and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [s for s in sections if s]


def _looks_like_error_table(table: Table) -> bool:
    headers = " ".join(table.headers).lower()
    return "error" in headers and "code" in headers


def _dedupe_prefer_table_rows(chunks: list[Chunk]) -> list[Chunk]:
    """Drop prose chunks whose error codes are already covered by table rows."""
    table_codes = {c for ch in chunks if ch.kind == "table_row" for c in ch.error_codes}
    out: list[Chunk] = []
    for chunk in chunks:
        covered = (
            chunk.kind != "table_row"
            and chunk.error_codes
            and set(chunk.error_codes) <= table_codes
            and len(chunk.text) < 120
        )
        if covered:
            continue
        out.append(chunk)
    return out


def _make_chunk(
    *,
    text: str,
    page: int,
    kind: str,
    error_codes: list[str],
    language: str | None,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    extractor: str | None,
    metadata: dict | None = None,
) -> Chunk:
    digest = hashlib.sha256(f"{page}:{kind}:{text}".encode()).hexdigest()[:12]
    meta = dict(metadata or {})
    if extractor:
        meta["extractor"] = extractor
    return Chunk(
        chunk_id=f"p{page}-{kind}-{digest}",
        text=text,
        page=page,
        kind=kind,
        error_codes=error_codes,
        language=language,
        doc_id=doc_id,
        publication_number=publication_number,
        revision=revision,
        metadata=meta,
    )
