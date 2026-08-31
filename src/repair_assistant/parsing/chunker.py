"""Turn an ExtractedDocument into retrieval chunks.

Table rows become one chunk each with error codes in structured metadata.
Prose uses heading-aware sections. Chunk text includes positional ancestry
(document label, section, table headers) per ADR-0022.
"""

from __future__ import annotations

import hashlib
import re

from .error_codes import extract_error_codes
from .language import is_index_language
from .models import Chunk, ExtractedDocument, Table
from .page_classify import (
    looks_like_figure_page,
    looks_like_junk_table,
    looks_like_schematic_page,
)
from .pua import map_pua, split_list_items
from .table_context import (
    ColumnMap,
    ContextualTableRow,
    detect_column_map,
    extract_guide_title,
    format_matrix_row_body,
    is_troubleshooting_guide_prose,
    is_troubleshooting_matrix,
    iter_contextual_rows,
    parse_troubleshooting_prose,
)

_HEADING_RE = re.compile(
    r"^(TABLE OF CONTENTS|SECTION\s+\d+\b|"
    r"FOR SERVICE TECHNICIAN|DIAGNOSTIC|TEST #\d|ERROR CODE|IMPORTANT|"
    r"WARNING|ABBREVIATIONS|TECHNICAL SERVICE POINTER|"
    r"FAULT/?\s*ERROR CODES?|MANUALLY UNLOCKING|MEASURED VALUES|"
    r"COMPONENT (?:LOCATION|TESTING)|WIRE HARNESS|"
    r"SENSOR|THERMISTOR|RESISTANCE)",
    re.IGNORECASE,
)
# Contents rows: "TEST #8: … .............. 3-15" — not procedure headings.
_TOC_LEADER_RE = re.compile(r"\.{4,}\s*\d+(?:-\d+)?\s*$")
_RUNNING_HEADER_RE = re.compile(
    r"^(TABLE OF CONTENTS|DIAGNOSTICS\s*&\s*TROUBLESHOOTING|"
    r"COMPONENT TESTING|COMPONENT ACCESS|CONNECTIVITY|"
    r"GENERAL INFORMATION|SECTION\s+\d+)\b",
    re.I,
)
_BANNER_HEADING_RE = re.compile(
    r"^(TABLE OF CONTENTS|SECTION\s+\d+|TEST #\d|"
    r"DIAGNOSTICS\b|DIAGNOSTIC MODE|ACTIVATING SERVICE DIAGNOSTIC|"
    r"COMPONENT (?:LOCATION|TESTING)|FAULT)",
    re.I,
)
_NOTE_BODY_RE = re.compile(
    r"\b(will|should|must|may|turn off|disconnect|prior to|otherwise|"
    r"the appliance|continue to step)\b",
    re.I,
)


def is_section_heading(line: str) -> bool:
    """True for procedure/section banners, not TOC rows or note sentences."""
    stripped = (line or "").strip()
    if not stripped or _TOC_LEADER_RE.search(stripped):
        return False
    if re.match(r"^FOR SERVICE TECHNICIAN", stripped, re.I):
        return False
    if re.fullmatch(r"(WARNING|DANGER|IMPORTANT):?", stripped, re.I):
        return False
    if re.match(r"^diagnostic voltage\b", stripped, re.I):
        return False
    if not _HEADING_RE.match(stripped):
        return False
    if _BANNER_HEADING_RE.match(stripped):
        return True
    if _NOTE_BODY_RE.search(stripped):
        return False
    if "." in stripped and len(stripped) > 40:
        return False
    return len(stripped) <= 90


def page_banner_section(text: str | None) -> str | None:
    """Running header near the top of a page, if present."""
    for line in (text or "").splitlines()[:8]:
        stripped = line.strip()
        match = _RUNNING_HEADER_RE.match(stripped)
        if match:
            return match.group(0).strip()
    return None


def chunk_document(
    document: ExtractedDocument,
    *,
    doc_id: str | None = None,
    publication_number: str | None = None,
    revision: str | None = None,
    doc_title: str | None = None,
    doc_type: str | None = None,
    strategy: str = "structured",
) -> list[Chunk]:
    """Chunk ``document``.

    ``strategy``:
      - ``structured`` — table rows + heading/prose (production path)
      - ``naive_fixed`` — fixed-size windows on raw page text (baseline)
    """
    if strategy == "naive_fixed":
        return _naive_fixed_chunks(document, doc_id, publication_number, revision)
    return _structured_chunks(
        document,
        doc_id,
        publication_number,
        revision,
        doc_title=doc_title,
        doc_type=doc_type,
    )


def format_contextual_text(
    *,
    body: str,
    doc_title: str | None = None,
    publication_number: str | None = None,
    revision: str | None = None,
    section: str | None = None,
    headers: list[str] | None = None,
    kind: str = "prose",
    table_group: str | None = None,
    table_group_note: str | None = None,
    guide_title: str | None = None,
) -> str:
    """Build embed/LLM text: ancestry prefix + body (ADR-0022)."""
    body = (body or "").strip()
    label = _doc_label(doc_title, publication_number, revision)
    prefix_parts: list[str] = []
    if label:
        prefix_parts.append(f"[{label}]")
    if section:
        prefix_parts.append(f"Section: {section}")
    if guide_title:
        prefix_parts.append(f"Guide: {guide_title}")
    if table_group:
        prefix_parts.append(f"Table group: {table_group}")
    if table_group_note:
        prefix_parts.append(f"Group note: {table_group_note}")

    if kind == "table_row" and headers:
        cells = [c.strip() for c in body.split(" | ")] if " | " in body else [body]
        if _body_already_keyed(cells, headers):
            pass
        elif len(headers) == len(cells):
            body = " | ".join(
                f"{h.strip()}: {c}" for h, c in zip(headers, cells, strict=False) if c
            )
        elif headers and not any(h in body for h in headers if h):
            prefix_parts.append("Headers: " + " | ".join(h for h in headers if h))

    prefix = " ".join(prefix_parts).strip()
    if not prefix:
        return body
    if body and body.startswith(prefix):
        return body
    return f"{prefix}\n{body}" if body else prefix


def _doc_label(
    doc_title: str | None,
    publication_number: str | None,
    revision: str | None,
) -> str:
    if publication_number:
        rev = f" Rev {revision}" if revision else ""
        return f"{publication_number}{rev}"
    if doc_title:
        return doc_title.strip()
    return ""


def _body_already_keyed(cells: list[str], headers: list[str]) -> bool:
    """True only when each cell is already ``Header: value`` for our headers."""
    if len(cells) != len(headers) or not headers:
        return False
    for header, cell in zip(headers, cells, strict=False):
        h = header.strip()
        if not h:
            return False
        if not (cell.startswith(f"{h}: ") or cell.startswith(f"{h}:")):
            return False
    return True


def _structured_chunks(
    document: ExtractedDocument,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    *,
    doc_title: str | None,
    doc_type: str | None,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_section: str | None = None

    for page in document.pages:
        if not is_index_language(page.language):
            continue

        tables = [t for t in page.tables if not looks_like_junk_table(t)]
        skip_prose = looks_like_figure_page(page.text) or looks_like_schematic_page(
            page.text
        )
        if skip_prose and not tables:
            # Review R33: do not index diagram OCR. Tables on the same sheet
            # (strip-circuit pin rows) still go in.
            continue

        banner = page_banner_section(page.text)
        if banner:
            current_section = banner

        # Update section from page text before emitting chunks for this page.
        for line in (page.text or "").splitlines():
            stripped = line.strip()
            if is_section_heading(stripped):
                current_section = stripped

        prose_text = map_pua(page.text or "")
        if tables:
            prose_text = _strip_table_cells_from_prose(prose_text, tables)

        matrix_table_chunks = 0
        for table in tables:
            before = len(chunks)
            chunks.extend(
                _chunks_from_table(
                    table,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    language=page.language,
                    doc_title=doc_title,
                    doc_type=doc_type,
                    section=current_section,
                    guide_title=extract_guide_title(page.text),
                )
            )
            matrix_table_chunks += sum(
                1
                for c in chunks[before:]
                if c.metadata.get("matrix_type") == "troubleshooting"
            )

        # Page-level matrix prose fallback when extractors miss table grids.
        # Run on full page text (not _split_prose fragments) so guide/header
        # signals stay together. Same ContextualTableRow path as tables.
        page_matrix_rows = 0
        if matrix_table_chunks == 0 and is_troubleshooting_guide_prose(prose_text):
            before = len(chunks)
            chunks.extend(
                _chunks_from_troubleshooting_prose(
                    prose_text,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    language=page.language,
                    doc_title=doc_title,
                    doc_type=doc_type,
                    section=current_section,
                    page=page.number,
                    extractor=document.extractor,
                    guide_title=extract_guide_title(prose_text),
                )
            )
            page_matrix_rows = len(chunks) - before
            if page_matrix_rows:
                # Avoid also emitting the same page as a mega-prose chunk.
                continue

        if skip_prose:
            continue

        for piece in _split_prose(prose_text):
            if is_troubleshooting_guide_prose(piece):
                chunks.extend(
                    _chunks_from_troubleshooting_prose(
                        piece,
                        doc_id=doc_id,
                        publication_number=publication_number,
                        revision=revision,
                        language=page.language,
                        doc_title=doc_title,
                        doc_type=doc_type,
                        section=current_section,
                        page=page.number,
                        extractor=document.extractor,
                        guide_title=extract_guide_title(piece),
                    )
                )
                continue

            codes = extract_error_codes(piece)
            kind = "heading" if is_section_heading(piece.strip().splitlines()[0]) else "prose"
            if "•" in piece and len(split_list_items(piece)) > 1:
                kind = "procedure"
            first_line = piece.strip().splitlines()[0] if piece.strip() else ""
            if is_section_heading(first_line):
                current_section = first_line
                section_for_chunk = first_line
            else:
                section_for_chunk = current_section

            body = piece.strip()
            text = format_contextual_text(
                body=body,
                doc_title=doc_title,
                publication_number=publication_number,
                revision=revision,
                section=section_for_chunk if kind != "heading" else None,
                headers=None,
                kind=kind,
            )
            meta: dict = {
                "body_text": body,
                "section_path": [section_for_chunk] if section_for_chunk else [],
            }
            if doc_title:
                meta["doc_title"] = doc_title
            if doc_type:
                meta["doc_type"] = doc_type
            chunks.append(
                _make_chunk(
                    text=text,
                    page=page.number,
                    kind=kind,
                    error_codes=list(dict.fromkeys(codes)),
                    language=page.language,
                    doc_id=doc_id,
                    publication_number=publication_number,
                    revision=revision,
                    extractor=document.extractor,
                    metadata=meta,
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
    doc_title: str | None,
    doc_type: str | None,
    section: str | None,
    guide_title: str = "",
) -> list[Chunk]:
    if is_troubleshooting_matrix(table.headers):
        return _chunks_from_troubleshooting_table(
            table,
            doc_id=doc_id,
            publication_number=publication_number,
            revision=revision,
            language=language,
            doc_title=doc_title,
            doc_type=doc_type,
            section=section,
            guide_title=guide_title,
        )

    headers_lower = [h.lower() for h in table.headers]
    error_col = next(
        (i for i, h in enumerate(headers_lower) if "error" in h or "code" in h), 0
    )
    chunks: list[Chunk] = []
    for row in table.rows:
        cells = row.cells
        if not cells:
            continue
        code_cell = cells[error_col] if error_col < len(cells) else cells[0]
        codes = extract_error_codes(code_cell)
        if not codes and re.fullmatch(r"F\dE\d", code_cell.strip()):
            codes = [code_cell.strip()]
        body = " | ".join(c for c in cells if c)
        body = map_pua(body)
        if not body.strip():
            continue
        text = format_contextual_text(
            body=body,
            doc_title=doc_title,
            publication_number=publication_number,
            revision=revision,
            section=section,
            headers=list(table.headers),
            kind="table_row",
        )
        meta: dict = {
            "headers": list(table.headers),
            "body_text": body,
            "section_path": [section] if section else [],
        }
        if doc_title:
            meta["doc_title"] = doc_title
        if doc_type:
            meta["doc_type"] = doc_type
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
                metadata=meta,
            )
        )
    return chunks


def _chunks_from_troubleshooting_table(
    table: Table,
    *,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    language: str | None,
    doc_title: str | None,
    doc_type: str | None,
    section: str | None,
    guide_title: str = "",
) -> list[Chunk]:
    """One chunk per cause/check row with inherited problem or group context."""
    col = detect_column_map(table.headers)
    chunks: list[Chunk] = []
    for ctx in iter_contextual_rows(table, guide_title=guide_title):
        if ctx.role != "data":
            continue
        chunks.append(
            _chunk_from_matrix_row(
                ctx,
                col=col,
                page=table.page,
                doc_id=doc_id,
                publication_number=publication_number,
                revision=revision,
                language=language,
                doc_title=doc_title,
                doc_type=doc_type,
                section=section,
                extractor=None,
            )
        )
    return chunks


def _chunks_from_troubleshooting_prose(
    text: str,
    *,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    language: str | None,
    doc_title: str | None,
    doc_type: str | None,
    section: str | None,
    page: int,
    extractor: str | None,
    guide_title: str = "",
) -> list[Chunk]:
    """Fallback when extractors miss table boundaries on troubleshooting pages."""
    headers = ["Problem", "Possible cause", "Checks & tests"]
    col = detect_column_map(headers)
    chunks: list[Chunk] = []
    for ctx in parse_troubleshooting_prose(text):
        if ctx.role != "data":
            continue
        if guide_title and not ctx.guide_title:
            ctx.guide_title = guide_title
        chunks.append(
            _chunk_from_matrix_row(
                ctx,
                col=col,
                page=page,
                doc_id=doc_id,
                publication_number=publication_number,
                revision=revision,
                language=language,
                doc_title=doc_title,
                doc_type=doc_type,
                section=section,
                extractor=extractor,
            )
        )
    return chunks


def _chunk_from_matrix_row(
    ctx: ContextualTableRow,
    *,
    col: ColumnMap,
    page: int,
    doc_id: str | None,
    publication_number: str | None,
    revision: str | None,
    language: str | None,
    doc_title: str | None,
    doc_type: str | None,
    section: str | None,
    extractor: str | None,
) -> Chunk:
    body = format_matrix_row_body(ctx, col)
    body = map_pua(body)
    codes = extract_error_codes(body)
    text = format_contextual_text(
        body=body,
        doc_title=doc_title,
        publication_number=publication_number,
        revision=revision,
        section=section,
        headers=list(ctx.headers),
        kind="table_row",
        table_group=ctx.group_title or None,
        table_group_note=ctx.group_note or None,
        guide_title=ctx.guide_title or None,
    )
    section_path = [p for p in (section, ctx.guide_title, ctx.group_title) if p]
    meta: dict = {
        "headers": list(ctx.headers),
        "body_text": body,
        "section_path": section_path,
        "table_group": ctx.group_title,
        "table_group_note": ctx.group_note,
        "problem_title": ctx.problem_title,
        "problem_detail": ctx.problem_detail,
        "guide_title": ctx.guide_title,
        "matrix_kind": ctx.matrix_kind,
        "row_role": ctx.role,
        "matrix_type": "troubleshooting",
    }
    if doc_title:
        meta["doc_title"] = doc_title
    if doc_type:
        meta["doc_type"] = doc_type
    return _make_chunk(
        text=text,
        page=page,
        kind="table_row",
        error_codes=list(dict.fromkeys(codes)),
        language=language,
        doc_id=doc_id,
        publication_number=publication_number,
        revision=revision,
        extractor=extractor,
        metadata=meta,
    )


def _strip_table_cells_from_prose(prose: str, tables: list[Table]) -> str:
    """Remove lines that are exact copies of table cell strings (reduce dupes)."""
    cell_values: set[str] = set()
    for table in tables:
        for h in table.headers:
            if h and h.strip():
                cell_values.add(h.strip())
        for row in table.rows:
            for cell in row.cells:
                if cell and cell.strip():
                    cell_values.add(cell.strip())
    if not cell_values:
        return prose
    kept: list[str] = []
    for line in prose.splitlines():
        stripped = line.strip()
        if stripped and stripped in cell_values:
            continue
        # Drop pure "a | b | c" lines that match a full row join.
        if " | " in stripped:
            parts = [p.strip() for p in stripped.split("|")]
            if parts and all(p in cell_values for p in parts if p):
                continue
        kept.append(line)
    return "\n".join(kept)


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
        tables = [t for t in page.tables if not looks_like_junk_table(t)]
        skip_prose = looks_like_figure_page(page.text) or looks_like_schematic_page(
            page.text
        )
        if skip_prose and not tables:
            continue
        text = page.text or ""
        for start in range(0, max(len(text), 1), size):
            window = text[start : start + size]
            if not window.strip():
                continue
            codes = extract_error_codes(window)
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
                    metadata={"strategy": "naive_fixed", "size": size, "body_text": window},
                )
            )
    return chunks


def _split_prose(text: str) -> list[str]:
    if not text.strip():
        return []
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if is_section_heading(line.strip()) and current:
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
        body = str(chunk.metadata.get("body_text") or chunk.text)
        covered = (
            chunk.kind != "table_row"
            and chunk.error_codes
            and set(chunk.error_codes) <= table_codes
            and len(body) < 120
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
    from repair_assistant.parsing.pua import strip_nul_chars

    text = strip_nul_chars(text)
    digest = hashlib.sha256(f"{page}:{kind}:{text}".encode()).hexdigest()[:12]
    meta = strip_nul_chars(dict(metadata or {}))
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


__all__ = [
    "chunk_document",
    "format_contextual_text",
    "is_section_heading",
    "page_banner_section",
]
