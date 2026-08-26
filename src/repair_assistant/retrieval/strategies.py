"""Retrieval strategy runners for the bake-off."""

from __future__ import annotations

import re
from typing import Any

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.embeddings import Embedder
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.rank import RankedHit, filter_and_rank
from repair_assistant.retrieval.search import code_fetch, merge_hits, search, vector_fetch


def _appliance(raw: dict | None) -> Appliance | None:
    if not raw or not raw.get("model"):
        return None
    return Appliance(
        model=raw["model"],
        serial=raw.get("serial"),
        model_introduced=raw.get("model_introduced"),
    )


def _hits_from_ranked(ranked: list[RankedHit]) -> list[dict]:
    return [
        {
            "doc_id": h.doc_id,
            "chunk_id": h.chunk_id,
            "text": h.text,
            "page": h.page,
            "kind": h.kind,
            "error_codes": h.error_codes,
            "publication_number": h.publication_number,
            "revision": h.revision,
            "score": h.final_score,
        }
        for h in ranked
    ]


def _rrf(rank_lists: list[list[dict]], *, k: int = 60) -> list[dict]:
    scores: dict[tuple[str, str], float] = {}
    payloads: dict[tuple[str, str], dict] = {}
    for ranked in rank_lists:
        for i, hit in enumerate(ranked):
            key = (hit["doc_id"], hit["chunk_id"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + i + 1)
            payloads.setdefault(key, hit)
    fused = []
    for key, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        row = dict(payloads[key])
        row["score"] = score
        fused.append(row)
    return fused


def _union_pool(
    vector_hits: list[dict],
    aux_hits: list[dict],
    *,
    weight: float = 1.0,
) -> list[dict]:
    """Union two candidate pools without collapsing scores onto a rank scale.

    RRF (see ``_rrf``) overwrites ``score`` with ~1/60-scale reciprocal ranks,
    which is an order of magnitude below the 0.02-0.35 boosts in
    ``filter_and_rank``. Boosts then dominate ranking outright. Here the vector
    arm keeps its true cosine similarity and the auxiliary arm is affine-mapped
    onto the observed vector band, so the combined pool stays on the scale the
    boosts were tuned against. Chunks found by both arms take the better score.
    """
    pool = [dict(h) for h in vector_hits]
    if not aux_hits:
        return pool

    scores = [float(h["score"]) for h in pool]
    vmax = max(scores) if scores else 1.0
    vmin = min(scores) if scores else 0.0
    amax = max(float(h["score"]) for h in aux_hits) or 1.0

    by_key = {(h["doc_id"], h["chunk_id"]): h for h in pool}
    for hit in aux_hits:
        mapped = vmin + (vmax - vmin) * weight * (float(hit["score"]) / amax)
        key = (hit["doc_id"], hit["chunk_id"])
        existing = by_key.get(key)
        if existing is not None:
            existing["score"] = max(float(existing["score"]), mapped)
            continue
        row = dict(hit)
        row["score"] = mapped
        pool.append(row)
        by_key[key] = row
    return pool


def query_literals(query: str) -> list[str]:
    """Mixed alphanumeric tokens from the query (part numbers, connectors, codes)."""
    out: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]{3,}", query):
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            out.append(token.upper())
    return list(dict.fromkeys(out))


def _apply_only(
    raw: list[dict],
    manifest: Manifest,
    appliance: Appliance | None,
    *,
    limit: int,
) -> list[RankedHit]:
    """Applicability filter without authority / error-code boosts."""
    by_id = {d.doc_id: d for d in manifest.documents}
    kept: list[RankedHit] = []
    for hit in raw:
        doc = by_id.get(hit["doc_id"])
        if appliance is not None:
            if doc is None:
                continue
            if not document_applies(doc.data, appliance):
                continue
        kept.append(
            RankedHit(
                doc_id=hit["doc_id"],
                chunk_id=hit["chunk_id"],
                text=hit["text"],
                page=hit.get("page"),
                kind=hit.get("kind"),
                error_codes=list(hit.get("error_codes") or []),
                publication_number=hit.get("publication_number"),
                revision=hit.get("revision"),
                score=float(hit["score"]),
                applies=True,
                apply_reason="",
                authority_boost=0.0,
            )
        )
    kept.sort(key=lambda h: h.score, reverse=True)
    return kept[:limit]


def lexical_fetch(db: Database, query: str, *, limit: int, include_synthetic: bool = True) -> list[dict]:
    synth_clause = "" if include_synthetic else "AND doc_id NOT LIKE 'synth-%%'"
    rows = db.fetchall(
        f"""
        SELECT
            doc_id,
            chunk_id,
            text,
            page,
            kind,
            error_codes,
            publication_number,
            revision,
            ts_rank_cd(
                to_tsvector('english', coalesce(text, '')),
                plainto_tsquery('english', %s)
            ) AS score
        FROM chunks
        WHERE to_tsvector('english', coalesce(text, ''))
              @@ plainto_tsquery('english', %s)
          {synth_clause}
        ORDER BY score DESC
        LIMIT %s
        """,
        (query, query, limit),
    )
    return [
        {
            "doc_id": r[0],
            "chunk_id": r[1],
            "text": r[2],
            "page": r[3],
            "kind": r[4],
            "error_codes": list(r[5] or []),
            "publication_number": r[6],
            "revision": r[7],
            "score": float(r[8] or 0.0),
        }
        for r in rows
    ]


_LEXICAL_COLUMNS = """
    doc_id, chunk_id, text, page, kind, error_codes, publication_number, revision
"""


def _rows_to_hits(rows: list[Any]) -> list[dict]:
    return [
        {
            "doc_id": r[0],
            "chunk_id": r[1],
            "text": r[2],
            "page": r[3],
            "kind": r[4],
            "error_codes": list(r[5] or []),
            "publication_number": r[6],
            "revision": r[7],
            "score": float(r[8] or 0.0),
        }
        for r in rows
    ]


def lexical_or_fetch(db: Database, query: str, *, limit: int) -> list[dict]:
    """Full-text search with OR semantics over the query's lexemes.

    ``lexical_fetch`` uses ``plainto_tsquery``, which ANDs every lexeme; a
    natural-language question therefore matches nothing in a terse table chunk.
    This variant relaxes the conjunction so the arm contributes recall instead
    of empty results.
    """
    rows = db.fetchall(
        f"""
        WITH q AS (
            SELECT to_tsquery(
                'english',
                nullif(replace(plainto_tsquery('english', %s)::text, ' & ', ' | '), '')
            ) AS tsq
        )
        SELECT {_LEXICAL_COLUMNS},
               ts_rank_cd(to_tsvector('english', coalesce(text, '')), q.tsq) AS score
        FROM chunks, q
        WHERE q.tsq IS NOT NULL
          AND to_tsvector('english', coalesce(text, '')) @@ q.tsq
        ORDER BY score DESC
        LIMIT %s
        """,
        (query, limit),
    )
    return _rows_to_hits(rows)


def literal_fetch(
    db: Database,
    query: str,
    *,
    limit: int,
    max_chunks: int = 40,
) -> list[dict]:
    """Exact-match recall for rare alphanumeric literals in the query.

    Generalises the hand-rolled ``code_fetch`` / ``connector_fetch`` side doors.
    Postgres ``ts_rank_cd`` carries no IDF term, so a once-occurring part number
    ranks below common words; rarity is therefore enforced directly by skipping
    any literal that appears in more than ``max_chunks`` chunks (model numbers,
    common step labels), which keeps the arm precise rather than noisy.
    """
    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for literal in query_literals(query):
        pattern = f"%{literal}%"
        (count_row,) = db.fetchall(
            "SELECT count(*) FROM chunks WHERE text ILIKE %s", (pattern,)
        )
        frequency = int(count_row[0] or 0)
        if frequency == 0 or frequency > max_chunks:
            continue
        rows = db.fetchall(
            f"""
            SELECT {_LEXICAL_COLUMNS}, 0.95 AS score
            FROM chunks
            WHERE text ILIKE %s
            LIMIT %s
            """,
            (pattern, limit),
        )
        for hit in _rows_to_hits(rows):
            key = (hit["doc_id"], hit["chunk_id"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)
    return hits


def run_strategy(
    strategy_id: str,
    db: Database,
    manifest: Manifest,
    fixture: dict[str, Any],
    *,
    k: int,
    overfetch: int,
    embedder: Embedder,
) -> list[dict]:
    query = fixture["question"]
    appliance = _appliance(fixture.get("appliance"))
    codes = extract_error_codes(query)

    if strategy_id == "vector_raw":
        vectors = embedder.embed([query])[0]
        return merge_hits(
            code_fetch(db, codes),
            vector_fetch(db, vectors, limit=k, include_synthetic=True),
        )[:k]

    if strategy_id == "vector_apply":
        vectors = embedder.embed([query])[0]
        raw = merge_hits(
            code_fetch(db, codes),
            vector_fetch(db, vectors, limit=overfetch, include_synthetic=True),
        )
        return _hits_from_ranked(_apply_only(raw, manifest, appliance, limit=k))

    if strategy_id == "vector_apply_boost":
        vectors = embedder.embed([query])[0]
        raw = merge_hits(
            code_fetch(db, codes),
            vector_fetch(db, vectors, limit=overfetch, include_synthetic=True),
        )
        ranked = filter_and_rank(
            raw, manifest, appliance, limit=k, query=query, query_error_codes=codes
        )
        return _hits_from_ranked(ranked)

    if strategy_id == "lexical_apply":
        raw = merge_hits(code_fetch(db, codes), lexical_fetch(db, query, limit=overfetch))
        ranked = filter_and_rank(
            raw, manifest, appliance, limit=k, query=query, query_error_codes=codes
        )
        return _hits_from_ranked(ranked)

    if strategy_id == "hybrid_rrf_apply":
        vectors = embedder.embed([query])[0]
        fused = merge_hits(
            code_fetch(db, codes),
            _rrf(
                [
                    vector_fetch(db, vectors, limit=overfetch, include_synthetic=True),
                    lexical_fetch(db, query, limit=overfetch),
                ]
            ),
        )
        ranked = filter_and_rank(
            fused, manifest, appliance, limit=k, query=query, query_error_codes=codes
        )
        return _hits_from_ranked(ranked)

    if strategy_id == "union_lexical_apply":
        vectors = embedder.embed([query])[0]
        pool = _union_pool(
            vector_fetch(db, vectors, limit=overfetch, include_synthetic=True),
            lexical_or_fetch(db, query, limit=overfetch),
        )
        ranked = filter_and_rank(
            merge_hits(code_fetch(db, codes), pool),
            manifest,
            appliance,
            limit=k,
            query=query,
            query_error_codes=codes,
        )
        return _hits_from_ranked(ranked)

    if strategy_id == "union_literal_apply":
        vectors = embedder.embed([query])[0]
        pool = _union_pool(
            vector_fetch(db, vectors, limit=overfetch, include_synthetic=True),
            literal_fetch(db, query, limit=overfetch),
        )
        ranked = filter_and_rank(
            merge_hits(code_fetch(db, codes), pool),
            manifest,
            appliance,
            limit=k,
            query=query,
            query_error_codes=codes,
        )
        return _hits_from_ranked(ranked)

    if strategy_id == "production_search":
        # Full ask/diagnose retrieval path (side doors included). Bake-off may
        # include synthetics; production callers leave include_synthetic false.
        allow_synth = fixture.get("source") == "synthetic"
        result = search(
            db,
            manifest,
            query,
            appliance=appliance,
            limit=k,
            overfetch=overfetch,
            embedder=embedder,
            include_synthetic=allow_synth,
        )
        return [
            {
                "doc_id": h.doc_id,
                "chunk_id": h.chunk_id,
                "text": h.text,
                "page": h.page,
                "kind": h.kind,
                "error_codes": list(h.error_codes or []),
                "publication_number": h.publication_number,
                "revision": h.revision,
                "score": float(h.score),
            }
            for h in result.hits
        ]

    raise KeyError(f"unknown strategy: {strategy_id}")


def default_embedder() -> Embedder:
    from repair_assistant.ingest.embeddings import get_shared_embedder
    from repair_assistant.ingest.env import embedding_model

    return get_shared_embedder(model=embedding_model())
