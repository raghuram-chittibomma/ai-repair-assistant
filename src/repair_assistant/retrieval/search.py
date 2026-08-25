"""Vector search over ingested chunks (pgvector + local BGE)."""

from __future__ import annotations

from dataclasses import dataclass, field

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.embeddings import Embedder, LocalEmbedder, build_embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import code_to_spaced_regex
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.rank import RankedHit, filter_and_rank


@dataclass
class Hit:
    doc_id: str
    chunk_id: str
    text: str
    page: int | None
    kind: str | None
    error_codes: list[str]
    publication_number: str | None
    revision: str | None
    score: float
    apply_reason: str = ""


@dataclass
class SearchResult:
    query: str
    hits: list[Hit] = field(default_factory=list)
    fetched: int = 0
    filtered_out: int = 0


def _row_to_hit(row: tuple) -> dict:
    return {
        "doc_id": row[0],
        "chunk_id": row[1],
        "text": row[2],
        "page": row[3],
        "kind": row[4],
        "error_codes": list(row[5] or []),
        "publication_number": row[6],
        "revision": row[7],
        "score": float(row[8]),
    }


def vector_fetch(
    db: Database,
    query_vector: list[float],
    *,
    limit: int,
) -> list[dict]:
    """Return raw hit dicts ordered by cosine similarity (higher is better)."""
    if not query_vector:
        return []
    vec = str(query_vector)
    rows = db.fetchall(
        """
        SELECT
            doc_id,
            chunk_id,
            text,
            page,
            kind,
            error_codes,
            publication_number,
            revision,
            1 - (embedding <=> %s::vector) AS score
        FROM chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec, vec, limit),
    )
    return [_row_to_hit(row) for row in rows]


def code_fetch(db: Database, codes: list[str], *, limit: int = 30) -> list[dict]:
    """Exact / spaced fault-code recall (MindTouch 'F5 E2' and metadata arrays)."""
    if not codes:
        return []
    pattern = "|".join(code_to_spaced_regex(c) for c in codes)
    rows = db.fetchall(
        """
        SELECT
            doc_id,
            chunk_id,
            text,
            page,
            kind,
            error_codes,
            publication_number,
            revision,
            1.0 AS score
        FROM chunks
        WHERE error_codes && %s::text[]
           OR text ~* %s
        ORDER BY
            CASE WHEN kind = 'article' THEN 0 ELSE 1 END,
            COALESCE(cardinality(error_codes), 99) ASC,
            doc_id
        LIMIT %s
        """,
        (codes, pattern, limit),
    )
    out = []
    for row in rows:
        hit = _row_to_hit(row)
        # Spaced MindTouch titles may lack metadata until re-parse; attach query codes
        # so ranking boosts still fire.
        hit["error_codes"] = sorted(set(hit["error_codes"]) | set(codes))
        out.append(hit)
    return out


def merge_hits(*lists: list[dict]) -> list[dict]:
    """Dedupe by (doc_id, chunk_id); earlier lists win on score."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for hits in lists:
        for hit in hits:
            key = (hit["doc_id"], hit["chunk_id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
    return out


def search(
    db: Database,
    manifest: Manifest,
    query: str,
    *,
    appliance: Appliance | None = None,
    limit: int = 8,
    overfetch: int = 40,
    embedder: Embedder | None = None,
) -> SearchResult:
    """Embed query, fetch neighbours, apply applicability + light precedence boosts."""
    embedder = embedder or build_embedder(skip=False, model=embedding_model())
    vectors = embedder.embed([query])
    if not vectors or not vectors[0]:
        return SearchResult(query=query)

    codes = extract_error_codes(query)
    raw = merge_hits(
        code_fetch(db, codes),
        vector_fetch(db, vectors[0], limit=max(overfetch, limit)),
    )
    all_ranked = filter_and_rank(
        raw,
        manifest,
        appliance,
        limit=len(raw),
        query_error_codes=codes,
    )
    filtered_out = (len(raw) - len(all_ranked)) if appliance is not None else 0
    ranked = all_ranked[:limit]
    hits = [
        Hit(
            doc_id=h.doc_id,
            chunk_id=h.chunk_id,
            text=h.text,
            page=h.page,
            kind=h.kind,
            error_codes=h.error_codes,
            publication_number=h.publication_number,
            revision=h.revision,
            score=h.final_score,
            apply_reason=h.apply_reason,
        )
        for h in ranked
    ]
    return SearchResult(
        query=query,
        hits=hits,
        fetched=len(raw),
        filtered_out=filtered_out,
    )


__all__ = [
    "Hit",
    "LocalEmbedder",
    "RankedHit",
    "SearchResult",
    "code_fetch",
    "extract_error_codes",
    "merge_hits",
    "search",
    "vector_fetch",
]
