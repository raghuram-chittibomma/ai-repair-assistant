"""Ingestion version lifecycle: candidate → ready → active (ADR-0047).

A document's derived ingestion output is versioned. Exactly one version per
document is ``active``, enforced by the ``ingestion_versions_one_active``
partial unique index, and retrieval only ever reads the ``active_chunks`` view.
Cutover demotes before it promotes so the index is never transiently violated,
and commits once so there is no window where a document has no active version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repair_assistant.ingest.store import Database

STRATEGY_STRUCTURED = "structured"
STRATEGY_SEMANTIC = "semantic_llm"
STRATEGIES: tuple[str, ...] = (STRATEGY_STRUCTURED, STRATEGY_SEMANTIC)

STATUS_CANDIDATE = "candidate"
STATUS_READY = "ready"
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_ABANDONED = "abandoned"
STATUSES: tuple[str, ...] = (
    STATUS_CANDIDATE,
    STATUS_READY,
    STATUS_ACTIVE,
    STATUS_SUPERSEDED,
    STATUS_ABANDONED,
)

#: Statuses an operator may activate from. A ``candidate`` must reach ``ready``
#: (every unit approved) before it can serve traffic.
ACTIVATABLE: tuple[str, ...] = (STATUS_READY, STATUS_SUPERSEDED, STATUS_ACTIVE)

_COLUMNS = """
    id, doc_id, version, strategy, status, source_fingerprint,
    segmenter_model, prompt_version, created_at, activated_at,
    superseded_by, meta
"""


class LifecycleError(RuntimeError):
    """An ingestion version transition that would corrupt retrieval state."""


@dataclass(frozen=True)
class IngestionVersion:
    id: int
    doc_id: str
    version: int
    strategy: str
    status: str
    source_fingerprint: str = ""
    segmenter_model: str | None = None
    prompt_version: str | None = None
    created_at: datetime | None = None
    activated_at: datetime | None = None
    superseded_by: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_semantic(self) -> bool:
        return self.strategy == STRATEGY_SEMANTIC


def _row(row: tuple[Any, ...] | None) -> IngestionVersion | None:
    if row is None:
        return None
    meta = row[11] if isinstance(row[11], dict) else {}
    return IngestionVersion(
        id=int(row[0]),
        doc_id=str(row[1]),
        version=int(row[2]),
        strategy=str(row[3]),
        status=str(row[4]),
        source_fingerprint=str(row[5] or ""),
        segmenter_model=row[6],
        prompt_version=row[7],
        created_at=row[8],
        activated_at=row[9],
        superseded_by=int(row[10]) if row[10] is not None else None,
        meta=meta,
    )


def get_version_by_id(db: Database, version_id: int) -> IngestionVersion | None:
    return _row(
        db.fetchone(
            f"SELECT {_COLUMNS} FROM ingestion_versions WHERE id = %s",
            (version_id,),
        )
    )


def get_version(db: Database, doc_id: str, version: int) -> IngestionVersion | None:
    return _row(
        db.fetchone(
            f"SELECT {_COLUMNS} FROM ingestion_versions WHERE doc_id = %s AND version = %s",
            (doc_id, version),
        )
    )


def active_version(db: Database, doc_id: str) -> IngestionVersion | None:
    return _row(
        db.fetchone(
            f"SELECT {_COLUMNS} FROM ingestion_versions "
            f"WHERE doc_id = %s AND status = %s",
            (doc_id, STATUS_ACTIVE),
        )
    )


def list_versions(db: Database, doc_id: str) -> list[IngestionVersion]:
    rows = db.fetchall(
        f"SELECT {_COLUMNS} FROM ingestion_versions WHERE doc_id = %s ORDER BY version",
        (doc_id,),
    )
    out = [_row(r) for r in rows]
    return [v for v in out if v is not None]


def latest_semantic_version(db: Database, doc_id: str) -> IngestionVersion | None:
    """Most recent semantic version, whatever its status. The review target."""
    rows = [v for v in list_versions(db, doc_id) if v.is_semantic]
    return rows[-1] if rows else None


def next_version_number(db: Database, doc_id: str) -> int:
    row = db.fetchone(
        "SELECT coalesce(max(version), 0) + 1 FROM ingestion_versions WHERE doc_id = %s",
        (doc_id,),
    )
    return int(row[0]) if row else 1


def create_version(
    db: Database,
    doc_id: str,
    *,
    strategy: str,
    status: str,
    source_fingerprint: str = "",
    segmenter_model: str | None = None,
    prompt_version: str | None = None,
    meta: dict[str, Any] | None = None,
) -> IngestionVersion:
    """Insert a version row. Does not commit; the caller owns the transaction."""
    if strategy not in STRATEGIES:
        raise LifecycleError(f"unknown ingestion strategy {strategy!r}")
    if status not in STATUSES:
        raise LifecycleError(f"unknown ingestion status {status!r}")
    version = next_version_number(db, doc_id)
    row = db.fetchone(
        f"""
        INSERT INTO ingestion_versions (
            doc_id, version, strategy, status, source_fingerprint,
            segmenter_model, prompt_version, activated_at, meta
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            CASE WHEN %s THEN now() ELSE NULL END, %s::jsonb
        )
        RETURNING {_COLUMNS}
        """,
        (
            doc_id,
            version,
            strategy,
            status,
            source_fingerprint,
            segmenter_model,
            prompt_version,
            status == STATUS_ACTIVE,
            json.dumps(meta or {}),
        ),
    )
    created = _row(row)
    if created is None:  # pragma: no cover — RETURNING always yields a row
        raise LifecycleError(f"failed to create ingestion version for {doc_id}")
    return created


def create_candidate(
    db: Database,
    doc_id: str,
    *,
    strategy: str = STRATEGY_SEMANTIC,
    source_fingerprint: str = "",
    segmenter_model: str | None = None,
    prompt_version: str | None = None,
    meta: dict[str, Any] | None = None,
) -> IngestionVersion:
    """Open a new candidate version. The active version keeps serving traffic."""
    return create_version(
        db,
        doc_id,
        strategy=strategy,
        status=STATUS_CANDIDATE,
        source_fingerprint=source_fingerprint,
        segmenter_model=segmenter_model,
        prompt_version=prompt_version,
        meta=meta,
    )


def ensure_structured_active(
    db: Database,
    doc_id: str,
    *,
    source_fingerprint: str,
) -> IngestionVersion:
    """The version row that plain ``repair-corpus ingest`` writes into.

    Raises :class:`LifecycleError` when a semantic version is active, so routine
    re-ingest of the corpus cannot clobber a reviewed document (ADR-0047
    decision 6). Does not commit.
    """
    current = active_version(db, doc_id)
    if current is not None and current.strategy != STRATEGY_STRUCTURED:
        raise LifecycleError(
            f"{doc_id}: ingestion version {current.version} ({current.strategy}) is active. "
            f"Run `repair-corpus ingestion-revert {doc_id}` before re-ingesting structured chunks."
        )
    if current is not None:
        db.execute(
            "UPDATE ingestion_versions SET source_fingerprint = %s WHERE id = %s",
            (source_fingerprint, current.id),
        )
        return replace(current, source_fingerprint=source_fingerprint)

    existing = [v for v in list_versions(db, doc_id) if v.strategy == STRATEGY_STRUCTURED]
    if existing:
        # A structured version exists but is not active, and nothing else is
        # either (no active row) — reactivate rather than pile up versions.
        reused = existing[-1]
        db.execute(
            """
            UPDATE ingestion_versions
            SET status = %s, source_fingerprint = %s, activated_at = now(), superseded_by = NULL
            WHERE id = %s
            """,
            (STATUS_ACTIVE, source_fingerprint, reused.id),
        )
        refreshed = get_version_by_id(db, reused.id)
        if refreshed is None:  # pragma: no cover
            raise LifecycleError(f"{doc_id}: structured version vanished mid-transaction")
        return refreshed

    return create_version(
        db,
        doc_id,
        strategy=STRATEGY_STRUCTURED,
        status=STATUS_ACTIVE,
        source_fingerprint=source_fingerprint,
    )


def set_status(db: Database, version_id: int, status: str) -> IngestionVersion:
    """Move a version between non-active statuses. Commits."""
    if status not in STATUSES:
        raise LifecycleError(f"unknown ingestion status {status!r}")
    if status == STATUS_ACTIVE:
        return activate(db, version_id)
    version = get_version_by_id(db, version_id)
    if version is None:
        raise LifecycleError(f"ingestion version {version_id} does not exist")
    if version.status == STATUS_ACTIVE:
        raise LifecycleError(
            f"{version.doc_id}: version {version.version} is active. "
            "Activate a replacement or revert instead of demoting it directly."
        )
    db.execute(
        "UPDATE ingestion_versions SET status = %s WHERE id = %s",
        (status, version_id),
    )
    db.commit()
    refreshed = get_version_by_id(db, version_id)
    if refreshed is None:  # pragma: no cover
        raise LifecycleError(f"ingestion version {version_id} vanished")
    return refreshed


def mark_ready(db: Database, version_id: int) -> IngestionVersion:
    """Human review finished and every unit approved. Not yet serving traffic."""
    return set_status(db, version_id, STATUS_READY)


def abandon(db: Database, version_id: int) -> IngestionVersion:
    """Give up on a candidate. The active version is untouched."""
    return set_status(db, version_id, STATUS_ABANDONED)


def activate(db: Database, version_id: int) -> IngestionVersion:
    """Cut over to ``version_id`` in one transaction.

    Demotes the outgoing version first: the partial unique index is checked per
    statement, so promoting first would fail. The single commit means retrieval
    never observes a document with zero active versions.
    """
    incoming = get_version_by_id(db, version_id)
    if incoming is None:
        raise LifecycleError(f"ingestion version {version_id} does not exist")
    if incoming.status == STATUS_ACTIVE:
        return incoming
    if incoming.status not in ACTIVATABLE:
        raise LifecycleError(
            f"{incoming.doc_id}: version {incoming.version} is {incoming.status!r}; "
            f"only {', '.join(ACTIVATABLE)} may be activated"
        )

    outgoing = active_version(db, incoming.doc_id)
    if outgoing is not None and outgoing.id != incoming.id:
        db.execute(
            """
            UPDATE ingestion_versions
            SET status = %s, superseded_by = %s
            WHERE id = %s
            """,
            (STATUS_SUPERSEDED, incoming.id, outgoing.id),
        )
    db.execute(
        """
        UPDATE ingestion_versions
        SET status = %s, activated_at = now(), superseded_by = NULL
        WHERE id = %s
        """,
        (STATUS_ACTIVE, incoming.id),
    )
    db.commit()
    refreshed = get_version_by_id(db, version_id)
    if refreshed is None:  # pragma: no cover
        raise LifecycleError(f"ingestion version {version_id} vanished mid-cutover")
    return refreshed


def revert_to(db: Database, doc_id: str, version: int) -> IngestionVersion:
    """Activate an earlier version. A rollback, not a re-parse.

    The source PDF and ``corpus/parsed/`` are never touched: superseded chunk
    rows are still stored, so this only moves which version the view selects.
    """
    target = get_version(db, doc_id, version)
    if target is None:
        raise LifecycleError(f"{doc_id}: no ingestion version {version}")
    if target.status == STATUS_ABANDONED:
        raise LifecycleError(
            f"{doc_id}: version {version} was abandoned and has no indexed chunks"
        )
    return activate(db, target.id)
