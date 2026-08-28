"""Postgres access for migrations and chunk upserts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repair_assistant.ingest.parsed import ParsedChunk, ParsedDocument


def _sql_dir() -> Path:
    return Path(__file__).resolve().parent / "sql"


@dataclass
class DocumentRow:
    doc_id: str
    content_fingerprint: str
    chunk_count: int


class Database:
    def __init__(self, url: str) -> None:
        import psycopg

        self._url = url
        self._conn = psycopg.connect(url, autocommit=False)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def fetchone(self, sql: str, params: Sequence[Any] | None = None) -> tuple[Any, ...] | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def commit(self) -> None:
        self._conn.commit()

    def get_document(self, doc_id: str) -> DocumentRow | None:
        row = self.fetchone(
            "SELECT doc_id, content_fingerprint, chunk_count FROM documents WHERE doc_id = %s",
            (doc_id,),
        )
        if not row:
            return None
        return DocumentRow(doc_id=row[0], content_fingerprint=row[1], chunk_count=row[2])

    def existing_chunk_hashes(self, doc_id: str) -> dict[str, str]:
        """Map chunk_id → content_hash for a document."""
        rows = self.fetchall(
            "SELECT chunk_id, content_hash FROM chunks WHERE doc_id = %s",
            (doc_id,),
        )
        return {r[0]: r[1] for r in rows}

    def chunks_missing_embeddings(self, doc_id: str) -> list[tuple[str, str]]:
        """Return (chunk_id, text) for rows with NULL embedding."""
        rows = self.fetchall(
            "SELECT chunk_id, text FROM chunks WHERE doc_id = %s AND embedding IS NULL",
            (doc_id,),
        )
        return [(r[0], r[1]) for r in rows]

    def upsert_document(self, parsed: ParsedDocument, corpus_sha256: str | None) -> None:
        meta = parsed.meta
        self.execute(
            """
            INSERT INTO documents (
                doc_id, publication_number, revision, source_filename, extractor,
                corpus_sha256, chunk_count, content_fingerprint, ingested_at, meta
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, now(), %s::jsonb
            )
            ON CONFLICT (doc_id) DO UPDATE SET
                publication_number = EXCLUDED.publication_number,
                revision = EXCLUDED.revision,
                source_filename = EXCLUDED.source_filename,
                extractor = EXCLUDED.extractor,
                corpus_sha256 = EXCLUDED.corpus_sha256,
                chunk_count = EXCLUDED.chunk_count,
                content_fingerprint = EXCLUDED.content_fingerprint,
                ingested_at = now(),
                meta = EXCLUDED.meta
            """,
            (
                parsed.doc_id,
                meta.get("publication_number")
                or (parsed.chunks[0].publication_number if parsed.chunks else None),
                meta.get("revision") or (parsed.chunks[0].revision if parsed.chunks else None),
                meta.get("source"),
                meta.get("extractor"),
                corpus_sha256,
                len(parsed.chunks),
                parsed.content_fingerprint,
                json.dumps(meta),
            ),
        )

    def replace_chunks(
        self,
        doc_id: str,
        chunks: list[ParsedChunk],
        *,
        keep_embeddings_for: set[str] | None = None,
    ) -> None:
        """Delete stale chunk_ids; upsert current rows. Optionally preserve embeddings."""
        keep_embeddings_for = keep_embeddings_for or set()
        wanted = {c.chunk_id for c in chunks}
        existing = self.existing_chunk_hashes(doc_id)
        stale = set(existing) - wanted
        if stale:
            self.execute(
                "DELETE FROM chunks WHERE doc_id = %s AND chunk_id = ANY(%s)",
                (doc_id, list(stale)),
            )

        for chunk in chunks:
            # Re-insert without wiping embedding if content_hash unchanged.
            if chunk.chunk_id in keep_embeddings_for:
                self.execute(
                    """
                    INSERT INTO chunks (
                        doc_id, chunk_id, content_hash, text, page, kind, error_codes,
                        language, publication_number, revision, metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT (doc_id, chunk_id) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        text = EXCLUDED.text,
                        page = EXCLUDED.page,
                        kind = EXCLUDED.kind,
                        error_codes = EXCLUDED.error_codes,
                        language = EXCLUDED.language,
                        publication_number = EXCLUDED.publication_number,
                        revision = EXCLUDED.revision,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        doc_id,
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
                    ),
                )
            else:
                self.execute(
                    """
                    INSERT INTO chunks (
                        doc_id, chunk_id, content_hash, text, page, kind, error_codes,
                        language, publication_number, revision, metadata, embedding, embedding_model
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NULL, NULL
                    )
                    ON CONFLICT (doc_id, chunk_id) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        text = EXCLUDED.text,
                        page = EXCLUDED.page,
                        kind = EXCLUDED.kind,
                        error_codes = EXCLUDED.error_codes,
                        language = EXCLUDED.language,
                        publication_number = EXCLUDED.publication_number,
                        revision = EXCLUDED.revision,
                        metadata = EXCLUDED.metadata,
                        embedding = NULL,
                        embedding_model = NULL
                    """,
                    (
                        doc_id,
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
                    ),
                )

    def set_embeddings(
        self,
        doc_id: str,
        vectors: Sequence[tuple[str, list[float]]],
        model: str,
    ) -> None:
        for chunk_id, vector in vectors:
            if not vector:
                continue
            self.execute(
                """
                UPDATE chunks
                SET embedding = %s::vector, embedding_model = %s
                WHERE doc_id = %s AND chunk_id = %s
                """,
                (str(vector), model, doc_id, chunk_id),
            )


def apply_migrations(db: Database) -> list[str]:
    """Apply pending SQL files under ingest/sql/. Returns applied version ids."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.commit()

    applied_rows = db.fetchall("SELECT version FROM schema_migrations")
    applied = {r[0] for r in applied_rows}
    done: list[str] = []
    sql_root = _sql_dir()
    for path in sorted(sql_root.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        # Skip re-creating schema_migrations (already ensured above).
        with db._conn.cursor() as cur:
            cur.execute(script)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (version,),
            )
        db.commit()
        done.append(version)
    return done
