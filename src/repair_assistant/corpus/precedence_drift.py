"""Detect missing precedence edges and stale revisions (review R19).

Uses only manifest metadata — never document bytes — so it is safe in CI.
Notices are informational; they do not fail ``repair-corpus validate``.
"""

from __future__ import annotations

from typing import Any

from repair_assistant.corpus.manifest import Document, Manifest

_PRECEDENCE = frozenset(
    {"corrects", "supersedes", "superseded_by", "overrides", "corrected_by"}
)


def _pub_date(document: Document) -> tuple[int, int, int] | None:
    temporal = document.data.get("temporal") or {}
    raw = temporal.get("publication_date")
    if raw is None:
        return None
    if isinstance(raw, int):
        return (raw, 0, 0)
    parts = str(raw).strip().split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 0
        day = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return (year, month, day)


def _rev_rank(revision: str | None) -> tuple[int, str]:
    if not revision:
        return (0, "")
    rev = revision.strip()
    if rev.isalpha():
        return (1, rev.upper())
    return (2, rev)


def is_newer_edition(candidate: Document, current: Document) -> bool:
    """True when candidate is a later edition of the same publication."""
    if candidate.publication_number != current.publication_number:
        return False
    if candidate.doc_id == current.doc_id:
        return False
    cand_date, cur_date = _pub_date(candidate), _pub_date(current)
    if cand_date and cur_date and cand_date != cur_date:
        return cand_date > cur_date
    return _rev_rank(candidate.revision) > _rev_rank(current.revision)


def newest_edition(manifest: Manifest, publication_number: str) -> Document | None:
    editions = manifest.by_publication(publication_number)
    if not editions:
        return None
    newest = editions[0]
    for doc in editions[1:]:
        if is_newer_edition(doc, newest):
            newest = doc
    return newest


def _blob(document: Document) -> str:
    """Searchable manifest text (no PDF)."""
    parts = [
        document.title,
        document.doc_id,
        str(document.data.get("notes") or ""),
        str((document.provenance or {}).get("access_notes") or ""),
    ]
    for rel in document.relationships():
        parts.append(str(rel.get("target") or ""))
        parts.append(str(rel.get("note") or ""))
        parts.append(str(rel.get("locator") or ""))
    return " ".join(parts)


def _has_precedence_edge(left: Document, right: Document) -> bool:
    pubs = {p for p in (left.publication_number, right.publication_number) if p}
    ids = {left.doc_id, right.doc_id}
    for doc in (left, right):
        for rel in doc.relationships():
            if rel.get("type") not in _PRECEDENCE:
                continue
            target = rel.get("target")
            if target in pubs or target in ids:
                return True
    return False


def drift_notices(manifest: Manifest) -> list[str]:
    """Missing edges: a newer entry names an older one, or two revisions are unlinked."""
    notices: list[str] = []
    docs = [d for d in manifest.documents if d.publication_number]
    by_pub: dict[str, list[Document]] = {}
    for doc in docs:
        by_pub.setdefault(doc.publication_number or "", []).append(doc)

    for pub, editions in sorted(by_pub.items()):
        if len(editions) < 2:
            continue
        linked = any(
            _has_precedence_edge(a, b)
            for i, a in enumerate(editions)
            for b in editions[i + 1 :]
        )
        if not linked:
            cites = ", ".join(sorted({e.citation for e in editions}))
            notices.append(
                f"R19: {pub} has multiple editions ({cites}) with no "
                "supersedes/corrects edge — the older revision may still be cited."
            )

    for newer in docs:
        newer_date = _pub_date(newer)
        if newer_date is None:
            continue
        blob = _blob(newer)
        for older in docs:
            if older.doc_id == newer.doc_id or not older.publication_number:
                continue
            if older.publication_number == newer.publication_number:
                continue
            older_date = _pub_date(older)
            if older_date is None or newer_date <= older_date:
                continue
            if older.publication_number.lower() not in blob.lower():
                continue
            if _has_precedence_edge(newer, older):
                continue
            notices.append(
                f"R19: {newer.citation} ({newer.path.name}) names "
                f"{older.publication_number} but has no precedence edge. "
                "If it corrects or supersedes that document, record the relationship."
            )
    return notices


def newer_revision_note(hits: list[Any], manifest: Manifest) -> str | None:
    """Staleness signal when a hit is not the newest edition in the corpus."""
    lines: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        pub = getattr(hit, "publication_number", None)
        if not pub or pub in seen:
            continue
        newest = newest_edition(manifest, pub)
        if newest is None:
            continue
        current = Document(
            data={
                "doc_id": getattr(hit, "doc_id", pub),
                "title": pub,
                "doc_type": "unknown",
                "corpus": {"role": "primary"},
                "publication_number": pub,
                "revision": getattr(hit, "revision", None),
            },
            path=newest.path,
        )
        if not is_newer_edition(newest, current):
            continue
        seen.add(pub)
        lines.append(
            f"A newer revision of {pub} is in the corpus ({newest.citation}). "
            "The cited passage may have been superseded."
        )
    return "\n".join(lines) if lines else None
