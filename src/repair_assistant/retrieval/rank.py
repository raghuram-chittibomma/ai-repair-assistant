"""Filter and re-rank vector hits using manifest applicability / precedence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Document, Manifest

_BIBLIOGRAPHIC = re.compile(
    r"\b(service manual|which manual|what manual|manual covers|covers a\b)\b",
    re.I,
)
_INSTALLATION = re.compile(
    r"\b(new washer|newly installed|just installed|shipping bolt|leveling|"
    r"shakes?|shaking|violently)\b",
    re.I,
)


def is_bibliographic_query(query: str) -> bool:
    """Lookup intent: which document applies, not how to repair a symptom."""
    return bool(_BIBLIOGRAPHIC.search(query))


def is_installation_query(query: str) -> bool:
    """Symptoms that often trace to installation faults rather than components."""
    return bool(_INSTALLATION.search(query))


@dataclass(frozen=True)
class RankedHit:
    doc_id: str
    chunk_id: str
    text: str
    page: int | None
    kind: str | None
    error_codes: list[str]
    publication_number: str | None
    revision: str | None
    score: float
    applies: bool
    apply_reason: str
    authority_boost: float = 0.0

    @property
    def final_score(self) -> float:
        return self.score + self.authority_boost


def _doc_by_id(manifest: Manifest) -> dict[str, Document]:
    return {d.doc_id: d for d in manifest.documents}


def _is_correcting_doc(doc: Document) -> bool:
    for rel in doc.relationships():
        if rel.get("type") in {"corrects", "supersedes", "overrides"}:
            return True
    tier = (doc.data.get("authority") or {}).get("tier")
    if tier in {"service_pointer", "technical_service_pointer"}:
        return True
    return doc.doc_type in {"technical_service_pointer", "service_pointer"}


def _reference_targets(hits: list[dict], by_id: dict[str, Document]) -> set[str]:
    """Publication numbers cited by KB articles already in the candidate pool."""
    targets: set[str] = set()
    for hit in hits:
        doc = by_id.get(hit["doc_id"])
        if doc is None or doc.doc_type != "knowledge_article":
            continue
        for rel in doc.relationships():
            if rel.get("type") == "references" and rel.get("target"):
                targets.add(str(rel["target"]))
    return targets


def filter_and_rank(
    hits: list[dict],
    manifest: Manifest,
    appliance: Appliance | None,
    *,
    limit: int,
    query: str = "",
    query_error_codes: list[str] | None = None,
) -> list[RankedHit]:
    """Drop inapplicable docs; boost correcting / pointer literature and error-code matches."""
    by_id = _doc_by_id(manifest)
    query_codes = {c.upper() for c in (query_error_codes or [])}
    bibliographic = is_bibliographic_query(query)
    installation = is_installation_query(query)
    ref_targets = _reference_targets(hits, by_id)

    ranked: list[RankedHit] = []
    for hit in hits:
        doc_id = hit["doc_id"]
        doc = by_id.get(doc_id)
        if appliance is not None and doc is not None:
            result = document_applies(doc.data, appliance)
            applies = result.applies
            reason = result.reason
        elif appliance is not None and doc is None:
            applies = False
            reason = "doc_id not in manifest"
        else:
            applies = True
            reason = "no appliance filter"

        if not applies:
            continue

        boost = 0.0
        if doc is not None:
            if not bibliographic:
                if _is_correcting_doc(doc):
                    boost += 0.05
                for rel in doc.relationships():
                    if rel.get("type") in {"corrects", "supersedes", "overrides"}:
                        boost += 0.08
                        break
            if doc.doc_type == "service_manual" and bibliographic:
                boost += 0.15
            if doc.doc_type == "installation_instructions" and installation:
                boost += 0.12
            tier = (doc.data.get("authority") or {}).get("tier")
            if tier in {"service_literature", "service_pointer", "technical_service_pointer"}:
                boost += 0.02

        pub = hit.get("publication_number")
        if ref_targets and pub and str(pub) in ref_targets:
            boost += 0.25
            if installation and query_codes:
                boost += 0.35
                if doc is not None and doc.doc_type == "installation_instructions":
                    boost += 0.15

        codes = [str(c).upper() for c in (hit.get("error_codes") or [])]
        kind = hit.get("kind") or ""
        if query_codes and query_codes.intersection(codes):
            boost += 0.15
            if set(codes) <= query_codes or len(set(codes)) <= 2:
                boost += 0.25
            if kind == "article":
                boost += 0.1
            if doc is not None and doc.doc_type == "knowledge_article":
                boost += 0.2

        ranked.append(
            RankedHit(
                doc_id=doc_id,
                chunk_id=hit["chunk_id"],
                text=hit["text"],
                page=hit.get("page"),
                kind=hit.get("kind"),
                error_codes=list(hit.get("error_codes") or []),
                publication_number=hit.get("publication_number"),
                revision=hit.get("revision"),
                score=float(hit["score"]),
                applies=applies,
                apply_reason=reason,
                authority_boost=boost,
            )
        )

    ranked.sort(key=lambda h: h.final_score, reverse=True)
    return _diverse_top(ranked, limit)


def _diverse_top(ranked: list[RankedHit], limit: int, *, max_per_doc: int = 2) -> list[RankedHit]:
    """Keep top scores while preventing one document from filling the entire window."""
    out: list[RankedHit] = []
    counts: dict[str, int] = {}
    for hit in ranked:
        n = counts.get(hit.doc_id, 0)
        if n >= max_per_doc:
            continue
        out.append(hit)
        counts[hit.doc_id] = n + 1
        if len(out) >= limit:
            break
    return out
