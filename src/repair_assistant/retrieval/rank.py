"""Filter and re-rank vector hits using manifest applicability / precedence."""

from __future__ import annotations

from dataclasses import dataclass

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Document, Manifest


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


def filter_and_rank(
    hits: list[dict],
    manifest: Manifest,
    appliance: Appliance | None,
    *,
    limit: int,
    query_error_codes: list[str] | None = None,
) -> list[RankedHit]:
    """Drop inapplicable docs; boost correcting / pointer literature and error-code matches."""
    by_id = _doc_by_id(manifest)
    query_codes = {c.upper() for c in (query_error_codes or [])}

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
            if _is_correcting_doc(doc):
                boost += 0.05
            for rel in doc.relationships():
                if rel.get("type") in {"corrects", "supersedes", "overrides"}:
                    boost += 0.08
                    break
            tier = (doc.data.get("authority") or {}).get("tier")
            if tier in {"service_literature", "service_pointer", "technical_service_pointer"}:
                boost += 0.02

        codes = [str(c).upper() for c in (hit.get("error_codes") or [])]
        if query_codes and query_codes.intersection(codes):
            boost += 0.1

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
    return ranked[:limit]
