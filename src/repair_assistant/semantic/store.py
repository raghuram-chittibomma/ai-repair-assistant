"""Persistence for semantic units, proposals, and representation rows.

Representations live in ``chunks`` with ``unit_id`` and ``rep_kind`` set, which
is what lets every existing retrieval arm find them without new SQL (ADR-0047).
Embedding is selective: a row is only re-embedded when its text actually changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from repair_assistant.ingest.parsed import ParsedChunk
from repair_assistant.semantic.representations import Representation
from repair_assistant.semantic.units import SemanticUnit

if TYPE_CHECKING:
    from repair_assistant.ingest.embeddings import Embedder
    from repair_assistant.ingest.store import Database

_UNIT_COLUMNS = """
    id, unit_key, ordinal, title, unit_type, page_start, page_end,
    section_path, source_text, source_span, content_hash, review_status,
    origin, edits, rationale, review_flag, review_note
"""


@dataclass
class EmbedStats:
    rows: int = 0
    embedded: int = 0
    skipped: int = 0
    over_limit: int = 0


def _unit_from_row(row: tuple[Any, ...]) -> SemanticUnit:
    section_path = row[7] if isinstance(row[7], list) else []
    source_span = row[9] if isinstance(row[9], list) else []
    edits = row[13] if isinstance(row[13], list) else []
    start_y, end_y = 0.0, 1.0
    span_ids = [str(a) for a in source_span]
    if len(span_ids) >= 2 and "@" in span_ids[0] and "@" in span_ids[1]:
        try:
            start_y = float(span_ids[0].split("@", 1)[1])
            end_y = float(span_ids[1].split("@", 1)[1])
        except ValueError:
            pass
    text = str(row[8] or "")
    return SemanticUnit(
        id=int(row[0]),
        unit_key=str(row[1]),
        ordinal=int(row[2]),
        title=str(row[3] or ""),
        unit_type=str(row[4] or "other"),
        page_start=row[5],
        page_end=row[6],
        section_path=[str(p) for p in section_path],
        source_text=text,
        source_span=span_ids,
        content_hash=str(row[10] or ""),
        review_status=str(row[11] or "proposed"),
        origin=str(row[12] or "llm"),
        edits=list(edits),
        rationale=str(row[14] or "") if len(row) > 14 else "",
        review_flag=str(row[15] or "none") if len(row) > 15 else "none",
        review_note=str(row[16] or "") if len(row) > 16 else "",
        start_y=start_y,
        end_y=end_y,
        needs_ocr=not bool(text.strip()),
    )


# --- proposals --------------------------------------------------------------


def record_proposal(
    db: Database,
    version_id: int,
    *,
    model: str,
    prompt_version: str,
    prompt_sha256: str = "",
    llm_input: dict[str, Any] | None = None,
    raw_output: str = "",
    validation: dict[str, Any] | None = None,
) -> int:
    """Store one segmentation run verbatim. The training-data substrate."""
    row = db.fetchone(
        """
        SELECT coalesce(max(attempt), 0) + 1 FROM semantic_proposals
        WHERE ingestion_version_id = %s
        """,
        (version_id,),
    )
    attempt = int(row[0]) if row else 1
    inserted = db.fetchone(
        """
        INSERT INTO semantic_proposals (
            ingestion_version_id, attempt, model, prompt_version, prompt_sha256,
            llm_input, raw_output, validation
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
        RETURNING id
        """,
        (
            version_id,
            attempt,
            model,
            prompt_version,
            prompt_sha256,
            json.dumps(llm_input or {}),
            raw_output,
            json.dumps(validation or {}),
        ),
    )
    return int(inserted[0]) if inserted else 0


def list_proposals(db: Database, version_id: int) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT id, attempt, model, prompt_version, validation, created_at
        FROM semantic_proposals
        WHERE ingestion_version_id = %s
        ORDER BY attempt
        """,
        (version_id,),
    )
    return [
        {
            "id": int(r[0]),
            "attempt": int(r[1]),
            "model": r[2],
            "prompt_version": r[3],
            "validation": r[4] if isinstance(r[4], dict) else {},
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


def training_export(db: Database, version_id: int) -> dict[str, Any]:
    """Everything needed to reconstruct proposal → correction → approved result.

    Not a fine-tuning implementation (ADR-0048 decision 8); the point is that the
    record is complete enough to build one later.
    """
    rows = db.fetchall(
        """
        SELECT attempt, model, prompt_version, llm_input, raw_output, validation
        FROM semantic_proposals
        WHERE ingestion_version_id = %s
        ORDER BY attempt
        """,
        (version_id,),
    )
    return {
        "ingestion_version_id": version_id,
        "proposals": [
            {
                "attempt": int(r[0]),
                "model": r[1],
                "prompt_version": r[2],
                "llm_input": r[3] if isinstance(r[3], dict) else {},
                "raw_output": r[4],
                "validation": r[5] if isinstance(r[5], dict) else {},
            }
            for r in rows
        ],
        "units": [u.to_json() for u in list_units(db, version_id)],
    }


# --- units ------------------------------------------------------------------


def insert_unit(db: Database, version_id: int, unit: SemanticUnit) -> SemanticUnit:
    """Insert one unit and stamp its id. Does not commit."""
    row = db.fetchone(
        """
        INSERT INTO semantic_units (
            ingestion_version_id, unit_key, ordinal, title, unit_type,
            page_start, page_end, section_path, source_text, source_span,
            content_hash, review_status, origin, edits,
            rationale, review_flag, review_note
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s::jsonb,
            %s, %s, %s
        )
        RETURNING id
        """,
        (
            version_id,
            unit.unit_key,
            unit.ordinal,
            unit.title,
            unit.unit_type,
            unit.page_start,
            unit.page_end,
            json.dumps(unit.section_path),
            unit.source_text,
            json.dumps(unit.source_span),
            unit.content_hash,
            unit.review_status,
            unit.origin,
            json.dumps(unit.edits),
            unit.rationale,
            unit.review_flag or "none",
            unit.review_note or "",
        ),
    )
    unit.id = int(row[0]) if row else None
    return unit


def replace_units(
    db: Database,
    version_id: int,
    units: list[SemanticUnit],
) -> list[SemanticUnit]:
    """Write a fresh unit set for a version. Does not commit."""
    db.execute(
        "DELETE FROM semantic_units WHERE ingestion_version_id = %s", (version_id,)
    )
    return [insert_unit(db, version_id, unit) for unit in units]


def list_units(db: Database, version_id: int) -> list[SemanticUnit]:
    rows = db.fetchall(
        f"""
        SELECT {_UNIT_COLUMNS} FROM semantic_units
        WHERE ingestion_version_id = %s ORDER BY ordinal
        """,
        (version_id,),
    )
    return [_unit_from_row(r) for r in rows]


def get_unit(db: Database, version_id: int, unit_key: str) -> SemanticUnit | None:
    row = db.fetchone(
        f"""
        SELECT {_UNIT_COLUMNS} FROM semantic_units
        WHERE ingestion_version_id = %s AND unit_key = %s
        """,
        (version_id, unit_key),
    )
    return _unit_from_row(row) if row else None


def update_unit(db: Database, version_id: int, unit: SemanticUnit) -> None:
    """Persist one edited unit. Does not commit."""
    db.execute(
        """
        UPDATE semantic_units SET
            title = %s, unit_type = %s, page_start = %s, page_end = %s,
            section_path = %s::jsonb, source_text = %s, source_span = %s::jsonb,
            content_hash = %s, review_status = %s, origin = %s, edits = %s::jsonb,
            rationale = %s, review_flag = %s, review_note = %s,
            ordinal = %s, updated_at = now()
        WHERE ingestion_version_id = %s AND unit_key = %s
        """,
        (
            unit.title,
            unit.unit_type,
            unit.page_start,
            unit.page_end,
            json.dumps(unit.section_path),
            unit.source_text,
            json.dumps(unit.source_span),
            unit.content_hash,
            unit.review_status,
            unit.origin,
            json.dumps(unit.edits),
            unit.rationale,
            unit.review_flag or "none",
            unit.review_note or "",
            unit.ordinal,
            version_id,
            unit.unit_key,
        ),
    )


def delete_unit(db: Database, version_id: int, unit_key: str) -> None:
    """Remove a unit and, by cascade, its representation rows."""
    db.execute(
        "DELETE FROM semantic_units WHERE ingestion_version_id = %s AND unit_key = %s",
        (version_id, unit_key),
    )


def all_units_approved(db: Database, version_id: int) -> bool:
    row = db.fetchone(
        """
        SELECT count(*) FROM semantic_units
        WHERE ingestion_version_id = %s AND review_status <> 'approved'
        """,
        (version_id,),
    )
    total = db.fetchone(
        "SELECT count(*) FROM semantic_units WHERE ingestion_version_id = %s",
        (version_id,),
    )
    return bool(total and int(total[0]) > 0 and row and int(row[0]) == 0)


# --- representation rows ---------------------------------------------------


def _representation_chunk(
    unit: SemanticUnit,
    rep: Representation,
    *,
    doc_id: str,
    publication_number: str | None,
    revision: str | None,
    error_codes: list[str] | None = None,
) -> ParsedChunk:
    """A ``chunks`` row that carries one representation's vector."""
    from repair_assistant.semantic.units import content_hash as unit_content_hash

    return ParsedChunk(
        chunk_id=rep.chunk_id,
        text=rep.text,
        page=unit.page_start,
        kind="semantic_rep",
        error_codes=list(error_codes or []),
        language="en-US",
        doc_id=doc_id,
        publication_number=publication_number,
        revision=revision,
        metadata={
            "rep_kind": rep.rep_kind,
            "unit_key": unit.unit_key,
            "unit_title": unit.title,
            "unit_type": unit.unit_type,
            "page_start": unit.page_start,
            "page_end": unit.page_end,
            "section_path": list(unit.section_path),
            "rep_tokens": rep.tokens,
            "rep_over_limit": rep.over_limit,
            "rep_origin": rep.origin,
            # Stamped so the review UI can say "this representation predates the
            # current boundary" without regenerating to find out.
            "unit_content_hash": unit.content_hash,
        },
        content_hash=unit_content_hash(rep.text, [rep.chunk_id]),
    )


def write_representations(
    db: Database,
    *,
    doc_id: str,
    version_id: int,
    unit: SemanticUnit,
    representations: list[Representation],
    publication_number: str | None = None,
    revision: str | None = None,
    error_codes: list[str] | None = None,
    prune: bool = True,
) -> int:
    """Upsert one unit's representation rows, preserving unchanged vectors.

    Over-limit representations are not indexed: embedding one would store the
    truncated vector this design exists to avoid. They stay visible to the
    reviewer through the unit payload.

    ``prune`` drops rows this call did not produce, which is what a full
    regeneration wants. A reviewer editing one kind passes ``prune=False`` so
    the kinds they did not touch survive.
    """
    if unit.id is None:
        raise ValueError(f"{unit.unit_key}: unit must be persisted before its rows")

    indexable = [r for r in representations if not r.over_limit and r.text.strip()]
    wanted = {r.chunk_id for r in indexable}

    existing = {
        str(r[0]): str(r[1])
        for r in db.fetchall(
            """
            SELECT chunk_id, content_hash FROM chunks
            WHERE ingestion_version_id = %s AND unit_id = %s
            """,
            (version_id, unit.id),
        )
    }
    if prune:
        stale = set(existing) - wanted
    else:
        # An edit that blew the budget still retires the row it replaced,
        # otherwise the old text keeps serving traffic under a new draft.
        touched = {r.chunk_id for r in representations}
        stale = touched - wanted
    if stale:
        db.execute(
            """
            DELETE FROM chunks
            WHERE ingestion_version_id = %s AND unit_id = %s AND chunk_id = ANY(%s)
            """,
            (version_id, unit.id, list(stale)),
        )

    for rep in indexable:
        chunk = _representation_chunk(
            unit,
            rep,
            doc_id=doc_id,
            publication_number=publication_number,
            revision=revision,
            error_codes=error_codes,
        )
        unchanged = existing.get(rep.chunk_id) == chunk.content_hash
        keep = {chunk.chunk_id} if unchanged else set()
        db.execute(
            """
            INSERT INTO chunks (
                doc_id, ingestion_version_id, unit_id, rep_kind, chunk_id,
                content_hash, text, page, kind, error_codes, language,
                publication_number, revision, metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (doc_id, ingestion_version_id, chunk_id) DO UPDATE SET
                unit_id = EXCLUDED.unit_id,
                rep_kind = EXCLUDED.rep_kind,
                content_hash = EXCLUDED.content_hash,
                text = EXCLUDED.text,
                page = EXCLUDED.page,
                kind = EXCLUDED.kind,
                error_codes = EXCLUDED.error_codes,
                language = EXCLUDED.language,
                publication_number = EXCLUDED.publication_number,
                revision = EXCLUDED.revision,
                metadata = EXCLUDED.metadata,
                embedding = CASE WHEN %s THEN chunks.embedding ELSE NULL END,
                embedding_model = CASE WHEN %s THEN chunks.embedding_model ELSE NULL END
            """,
            (
                doc_id,
                version_id,
                unit.id,
                rep.rep_kind,
                chunk.chunk_id,
                chunk.content_hash,
                chunk.text,
                chunk.page,
                chunk.kind,
                chunk.error_codes,
                chunk.language,
                chunk.publication_number,
                chunk.revision,
                json.dumps(chunk.metadata),
                bool(keep),
                bool(keep),
            ),
        )
    _record_rejected(db, version_id, unit, representations)
    return len(indexable)


#: Edit-trail action used for a representation that blew the token budget.
REJECTED_ACTION = "representation_rejected"


def _record_rejected(
    db: Database,
    version_id: int,
    unit: SemanticUnit,
    representations: list[Representation],
) -> None:
    """Keep an over-limit draft on the unit so the reviewer can still see it.

    The row is not indexed — embedding it would store exactly the truncated
    vector ADR-0048 exists to avoid — but silently dropping the text would give
    the reviewer nothing to shorten. Parking it in ``edits`` keeps it visible
    and makes the rejection part of the training trail.
    """
    rejected = [r for r in representations if r.over_limit and r.text.strip()]
    if not rejected:
        return
    unit.edits = [
        *unit.edits,
        *(
            {
                "action": REJECTED_ACTION,
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "rep_kind": rep.rep_kind,
                "tokens": rep.tokens,
                "origin": rep.origin,
                "text": rep.text,
            }
            for rep in rejected
        ),
    ]
    db.execute(
        "UPDATE semantic_units SET edits = %s::jsonb WHERE ingestion_version_id = %s AND unit_key = %s",
        (json.dumps(unit.edits), version_id, unit.unit_key),
    )


def embed_missing(
    db: Database,
    doc_id: str,
    *,
    version_id: int,
    embedder: Embedder,
) -> EmbedStats:
    """Embed only the rows whose text changed. Does not commit."""
    stats = EmbedStats()
    missing = db.chunks_missing_embeddings(doc_id, version_id=version_id)
    stats.rows = len(missing)
    if not missing or embedder.model == "none":
        return stats
    ids = [cid for cid, _ in missing]
    vectors = embedder.embed([text for _, text in missing])
    db.set_embeddings(
        doc_id,
        list(zip(ids, vectors, strict=True)),
        embedder.model,
        version_id=version_id,
    )
    stats.embedded = len(ids)
    return stats


def units_with_representations(
    db: Database,
    version_id: int,
) -> list[dict[str, Any]]:
    """Units plus their indexed representation rows, for the review UI."""
    units = list_units(db, version_id)
    rows = db.fetchall(
        """
        SELECT unit_id, rep_kind, text, metadata, embedding IS NOT NULL
        FROM chunks
        WHERE ingestion_version_id = %s AND unit_id IS NOT NULL
        ORDER BY unit_id, rep_kind
        """,
        (version_id,),
    )
    by_unit: dict[int, list[dict[str, Any]]] = {}
    hashes: dict[int, set[str]] = {}
    for row in rows:
        meta = row[3] if isinstance(row[3], dict) else {}
        unit_id = int(row[0])
        by_unit.setdefault(unit_id, []).append(
            {
                "rep_kind": row[1],
                "text": row[2],
                "tokens": meta.get("rep_tokens"),
                "over_limit": bool(meta.get("rep_over_limit")),
                "origin": meta.get("rep_origin", "llm"),
                "embedded": bool(row[4]),
            }
        )
        hashes.setdefault(unit_id, set()).add(str(meta.get("unit_content_hash") or ""))

    out: list[dict[str, Any]] = []
    for unit in units:
        payload = unit.to_json()
        key = unit.id or -1
        payload["representations"] = by_unit.get(key, [])
        indexed = {r["rep_kind"] for r in payload["representations"]}
        # Only surface a rejected draft for a kind that has nothing indexed; a
        # later successful regeneration supersedes it.
        rejected: dict[str, dict[str, Any]] = {}
        for entry in payload["edits"]:
            kind = entry.get("rep_kind")
            if entry.get("action") != REJECTED_ACTION or kind in indexed:
                continue
            rejected[kind] = {
                "rep_kind": kind,
                "text": entry.get("text", ""),
                "tokens": entry.get("tokens"),
                "over_limit": True,
                "origin": entry.get("origin", "llm"),
                "embedded": False,
            }
        payload["rejected_representations"] = list(rejected.values())
        # A boundary moved but the representations were not regenerated. Worth
        # showing rather than hiding: the reviewer decides whether to pay for it.
        payload["representations_stale"] = bool(
            payload["representations"] and hashes.get(key, set()) != {unit.content_hash}
        )
        out.append(payload)
    return out
