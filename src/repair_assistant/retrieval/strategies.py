"""Retrieval strategy runners for the bake-off."""

from __future__ import annotations

from typing import Any

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.embeddings import Embedder, build_embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.rank import RankedHit, filter_and_rank
from repair_assistant.retrieval.search import code_fetch, merge_hits, vector_fetch


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


def lexical_fetch(db: Database, query: str, *, limit: int) -> list[dict]:
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
            ts_rank_cd(
                to_tsvector('english', coalesce(text, '')),
                plainto_tsquery('english', %s)
            ) AS score
        FROM chunks
        WHERE to_tsvector('english', coalesce(text, ''))
              @@ plainto_tsquery('english', %s)
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
        return merge_hits(code_fetch(db, codes), vector_fetch(db, vectors, limit=k))[:k]

    if strategy_id == "vector_apply":
        vectors = embedder.embed([query])[0]
        raw = merge_hits(
            code_fetch(db, codes),
            vector_fetch(db, vectors, limit=overfetch),
        )
        return _hits_from_ranked(_apply_only(raw, manifest, appliance, limit=k))

    if strategy_id == "vector_apply_boost":
        vectors = embedder.embed([query])[0]
        raw = merge_hits(
            code_fetch(db, codes),
            vector_fetch(db, vectors, limit=overfetch),
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
                    vector_fetch(db, vectors, limit=overfetch),
                    lexical_fetch(db, query, limit=overfetch),
                ]
            ),
        )
        ranked = filter_and_rank(
            fused, manifest, appliance, limit=k, query=query, query_error_codes=codes
        )
        return _hits_from_ranked(ranked)

    raise KeyError(f"unknown strategy: {strategy_id}")


def default_embedder() -> Embedder:
    return build_embedder(skip=False, model=embedding_model())
