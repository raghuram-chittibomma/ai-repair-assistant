"""Build canonical document tree from extracted pages (ADR-0024)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .pua import map_pua

if TYPE_CHECKING:
    from repair_assistant.parsing.models import ExtractedDocument, Table, TableRow
    from repair_assistant.parsing.parse_quality import PageAudit

_HEADING_LINE = re.compile(
    r"^(FOR SERVICE TECHNICIAN|DIAGNOSTIC|TEST #\d|ERROR CODE|IMPORTANT|"
    r"WARNING|ABBREVIATIONS|TECHNICAL SERVICE POINTER|"
    r"FAULT/?\s*ERROR CODES?|MANUALLY UNLOCKING|MEASURED VALUES|"
    r"COMPONENT (?:LOCATION|TESTING)|WIRE HARNESS|"
    r"SENSOR|THERMISTOR|RESISTANCE)",
    re.IGNORECASE,
)


@dataclass
class DocumentNode:
    kind: str  # heading | paragraph | procedure | table | page
    text: str = ""
    page: int = 0
    children: list[DocumentNode] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CanonicalDocument:
    path: str
    extractor: str
    nodes: list[DocumentNode] = field(default_factory=list)
    page_audits: list[PageAudit] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "extractor": self.extractor,
            "nodes": [_node_to_json(n) for n in self.nodes],
            "page_audits": [
                {
                    "page": a.page,
                    "layout_kind": a.layout_kind,
                    "prose_source": a.prose_source,
                    "flags": a.flags,
                    "retried": a.retried,
                }
                for a in self.page_audits
            ],
        }


def _node_to_json(node: DocumentNode) -> dict:
    return {
        "kind": node.kind,
        "text": node.text,
        "page": node.page,
        "headers": node.headers,
        "rows": [{"cells": r.cells, "page": r.page} for r in node.rows],
        "metadata": node.metadata,
        "children": [_node_to_json(c) for c in node.children],
    }


def _split_prose_sections(text: str) -> list[tuple[str, str]]:
    """Return (kind, text) sections split on heading lines."""
    if not text.strip():
        return []
    sections: list[tuple[str, str]] = []
    current_kind = "paragraph"
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING_LINE.match(stripped) and current_lines:
            sections.append((current_kind, "\n".join(current_lines).strip()))
            current_lines = [line]
            current_kind = "heading" if _HEADING_LINE.match(stripped) else "paragraph"
        else:
            if stripped and _HEADING_LINE.match(stripped) and not current_lines:
                current_kind = "heading"
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            if re.search(r"^\d+\.\s", body, re.M) and "TEST #" in body.upper():
                sections.append(("procedure", body))
            else:
                sections.append((current_kind, body))
    return sections


def _table_node(table: Table) -> DocumentNode:
    return DocumentNode(
        kind="table",
        page=table.page,
        headers=list(table.headers),
        rows=list(table.rows),
        text=" | ".join(h for h in table.headers if h),
        metadata={"row_count": len(table.rows)},
    )


def build_canonical(
    document: ExtractedDocument,
    *,
    page_audits: list[PageAudit] | None = None,
) -> CanonicalDocument:
    nodes: list[DocumentNode] = []
    for page in document.pages:
        page_node = DocumentNode(kind="page", page=page.number, metadata={})
        text = map_pua(page.text or "")

        table_cell_set: set[str] = set()
        for table in page.tables:
            for h in table.headers:
                if h.strip():
                    table_cell_set.add(h.strip())
            for row in table.rows:
                for cell in row.cells:
                    if cell.strip():
                        table_cell_set.add(cell.strip())

        for kind, section in _split_prose_sections(text):
            lines = [ln for ln in section.splitlines() if ln.strip()]
            if not lines:
                continue
            # Skip prose that duplicates table cells only.
            if all(ln.strip() in table_cell_set for ln in lines if ln.strip()):
                continue
            page_node.children.append(
                DocumentNode(kind=kind, text=section, page=page.number)
            )

        for table in page.tables:
            page_node.children.append(_table_node(table))

        if page_node.children:
            nodes.append(page_node)

    return CanonicalDocument(
        path=document.path,
        extractor=document.extractor,
        nodes=nodes,
        page_audits=list(page_audits or []),
    )


__all__ = ["CanonicalDocument", "DocumentNode", "build_canonical"]
