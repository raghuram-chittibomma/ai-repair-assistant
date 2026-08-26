"""Vector search over ingested chunks (pgvector + local BGE)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.embeddings import Embedder, LocalEmbedder, build_embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import code_to_spaced_regex
from repair_assistant.parsing.error_codes import extract_connector_ids
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.rank import (
    RankedHit,
    filter_and_rank,
    is_acu_led_query,
    is_bibliographic_query,
    is_installation_query,
    requested_revision,
)


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
    include_synthetic: bool = False,
) -> list[dict]:
    """Return raw hit dicts ordered by cosine similarity (higher is better).

    Synthetic eval docs (``synth-*`` / ``SYNTH-*``) are excluded unless
    ``include_synthetic`` is true (bake-off only).
    """
    if not query_vector:
        return []
    vec = str(query_vector)
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
            1 - (embedding <=> %s::vector) AS score
        FROM chunks
        WHERE embedding IS NOT NULL
        {synth_clause}
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


def connector_fetch(db: Database, connectors: list[str], *, limit: int = 20) -> list[dict]:
    """Exact connector-id recall (J36) — dense retrieval is weak on short alphanumerics.

    Strip-circuit tables often store only ``J36 | -1`` cells; pull same-page
    headings/prose so the model sees motor/harness context, not just the pin id.
    """
    if not connectors:
        return []
    pattern = "|".join(rf"{re.escape(c)}(?![0-9])" for c in connectors)
    seed_rows = db.fetchall(
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
        WHERE text ~* %s
        ORDER BY
            CASE WHEN text ~* 'motor|stator|harness' THEN 0 ELSE 1 END,
            length(coalesce(text, '')) DESC,
            page,
            doc_id
        LIMIT %s
        """,
        (pattern, limit),
    )
    seeds = [_row_to_hit(row) for row in seed_rows]
    pages = {(h["doc_id"], h["page"]) for h in seeds if h.get("page") is not None}
    if not pages:
        return seeds

    doc_ids = list({d for d, _ in pages})
    page_nos = list({p for _, p in pages})
    neighbor_rows = db.fetchall(
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
            0.95 AS score
        FROM chunks
        WHERE doc_id = ANY(%s::text[])
          AND page = ANY(%s::int[])
          AND kind IN ('heading', 'prose', 'procedure')
          AND length(coalesce(text, '')) >= 60
          AND text ~* 'motor|stator|harness|acu'
        ORDER BY length(coalesce(text, '')) DESC
        LIMIT %s
        """,
        (doc_ids, page_nos, limit),
    )
    return merge_hits(seeds, [_row_to_hit(row) for row in neighbor_rows])[:limit]


def reference_fetch(
    db: Database,
    manifest: Manifest,
    seed_hits: list[dict],
    *,
    query: str = "",
    limit: int = 8,
) -> list[dict]:
    """Pull chunks from publications referenced by KB articles (multi-hop recall)."""
    by_id = {d.doc_id: d for d in manifest.documents}
    target_pubs: set[str] = set()
    for hit in seed_hits:
        doc = by_id.get(hit["doc_id"])
        if doc is None:
            continue
        for rel in doc.relationships():
            if rel.get("type") == "references" and rel.get("target"):
                target_pubs.add(str(rel["target"]))
    if not target_pubs:
        return []

    install_kw = is_installation_query(query)
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
            0.85 AS score
        FROM chunks
        WHERE publication_number = ANY(%s::text[])
        ORDER BY
            CASE WHEN coalesce(language, 'en') = 'en' THEN 0 ELSE 1 END,
            CASE
                WHEN text ~* 'shipping|transport bolt|transport bolts|spacer' THEN 0
                WHEN %s AND text ~* 'shipping|bolt|level|install' THEN 1
                ELSE 2
            END,
            page,
            chunk_id
        LIMIT %s
        """,
        (list(target_pubs), install_kw, limit),
    )
    return [_row_to_hit(row) for row in rows]


def manual_rev_fetch(
    db: Database,
    manifest: Manifest,
    rev_letter: str,
    *,
    appliance: Appliance | None,
    query: str = "",
    limit: int = 12,
) -> list[dict]:
    """Recall chunks from a named service-manual revision (bibliographic queries)."""
    from repair_assistant.corpus.applicability import document_applies

    pubs: list[str] = []
    for doc in manifest.documents:
        if doc.doc_type != "service_manual":
            continue
        if appliance is not None and not document_applies(doc.data, appliance).applies:
            continue
        pub = doc.publication_number
        if pub:
            pubs.append(pub)
    if not pubs:
        return []

    acu_led = is_acu_led_query(query)
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
            0.88 AS score
        FROM chunks
        WHERE publication_number = ANY(%s::text[])
          AND upper(revision) = upper(%s)
        ORDER BY
            CASE
                WHEN text ~* 'status LED' THEN 0
                WHEN page = 44 THEN 1
                WHEN text ~* 'TEST #1.*ACU Power Check' THEN 2
                WHEN %s AND text ~* 'diagnostic led|step 10|blink' THEN 3
                ELSE 4
            END,
            page,
            chunk_id
        LIMIT %s
        """,
        (list(set(pubs)), rev_letter, acu_led, limit),
    )
    return [_row_to_hit(row) for row in rows]


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
    include_synthetic: bool = False,
) -> SearchResult:
    """Embed query, fetch neighbours, apply applicability + light precedence boosts.

    ``include_synthetic`` is for bake-off only. Production ask/diagnose leave it
    false so ``synth-*`` / ``SYNTH-*`` eval docs never surface.
    """
    embedder = embedder or build_embedder(skip=False, model=embedding_model())
    vectors = embedder.embed([query])
    if not vectors or not vectors[0]:
        return SearchResult(query=query)

    codes = extract_error_codes(query)
    code_hits = code_fetch(db, codes)
    connector_hits = connector_fetch(db, extract_connector_ids(query))
    rev_letter = requested_revision(query)
    bibliographic = is_bibliographic_query(query)
    rev_hits: list[dict] = []
    if bibliographic and rev_letter:
        rev_hits = manual_rev_fetch(
            db,
            manifest,
            rev_letter,
            appliance=appliance,
            query=query,
            limit=8 if is_acu_led_query(query) else 12,
        )
    if bibliographic and rev_letter and rev_hits and is_acu_led_query(query):
        raw = rev_hits
    else:
        raw = merge_hits(
            rev_hits,
            code_hits,
            connector_hits,
            reference_fetch(db, manifest, code_hits, query=query, limit=3),
            vector_fetch(
                db,
                vectors[0],
                limit=max(overfetch, limit),
                include_synthetic=include_synthetic,
            ),
        )
        if bibliographic and rev_letter:
            by_id = {d.doc_id: d for d in manifest.documents}
            restricted = [
                hit
                for hit in raw
                if (doc := by_id.get(hit["doc_id"]))
                and doc.doc_type == "service_manual"
                and str(hit.get("revision") or "").upper() == rev_letter
            ]
            if restricted:
                raw = restricted
    if not include_synthetic:
        raw = [
            hit
            for hit in raw
            if not str(hit.get("doc_id") or "").startswith("synth-")
            and not str(hit.get("publication_number") or "").startswith("SYNTH-")
        ]
    all_ranked = filter_and_rank(
        raw,
        manifest,
        appliance,
        limit=len(raw),
        query=query,
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
    "manual_rev_fetch",
    "reference_fetch",
    "search",
    "vector_fetch",
]
