"""Vector search over ingested chunks (pgvector + local BGE)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.embeddings import Embedder, LocalEmbedder, build_embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.retrieval.rank import RankedHit, filter_and_rank

_ERROR_CODE = re.compile(r"\bF\dE\d\b", re.IGNORECASE)


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


def extract_error_codes(text: str) -> list[str]:
    return sorted({m.group(0).upper() for m in _ERROR_CODE.finditer(text)})


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
    out: list[dict] = []
    for row in rows:
        out.append(
            {
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
        )
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

    raw = vector_fetch(db, vectors[0], limit=max(overfetch, limit))
    # Rank all over-fetched hits; slice to limit after measuring filter drop.
    all_ranked = filter_and_rank(
        raw,
        manifest,
        appliance,
        limit=len(raw),
        query_error_codes=extract_error_codes(query),
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


# Re-export for type checkers / tests
__all__ = [
    "Hit",
    "LocalEmbedder",
    "RankedHit",
    "SearchResult",
    "extract_error_codes",
    "search",
    "vector_fetch",
]
