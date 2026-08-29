"""Link a diagnosis to part numbers already in the indexed parts list (R42)."""

from __future__ import annotations

import re

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Manifest

_PART_RE = re.compile(r"\bW\d{8}\b")


def applicable_parts_documents(manifest: Manifest, appliance: Appliance | None) -> list:
    if appliance is None:
        return []
    out = []
    for doc in manifest.documents:
        if doc.doc_type != "parts_list":
            continue
        if document_applies(doc.data, appliance):
            out.append(doc)
    return out


def related_parts_note(
    hits,
    manifest: Manifest | None,
    appliance: Appliance | None,
) -> str | None:
    """Name the applicable parts list and any part numbers already retrieved."""
    if manifest is None or appliance is None:
        return None
    docs = applicable_parts_documents(manifest, appliance)
    if not docs:
        return None
    ids = {d.doc_id for d in docs}
    pubs = {d.publication_number for d in docs if d.publication_number}
    numbers: list[str] = []
    for hit in hits:
        if getattr(hit, "doc_id", None) not in ids:
            continue
        for token in _PART_RE.findall(getattr(hit, "text", "") or ""):
            if token not in pubs and token not in numbers:
                numbers.append(token)
    cites = ", ".join(d.citation for d in docs)
    line = f"Parts list on file for this appliance: {cites}."
    if numbers:
        line += " Part numbers in retrieved parts-list evidence: " + ", ".join(numbers[:8]) + "."
    return line
