"""Filter and re-rank vector hits using manifest applicability / precedence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
_REVISION = re.compile(r"\brevision\s+([A-Z])\b", re.I)
_ACU_LED = re.compile(r"\bacu\b.*\bled\b|\bled\b.*\bacu\b", re.I)
# Whirlpool-family publication numbers as they appear in questions ("…of W11320651").
_PUBLICATION = re.compile(r"\b(W\d{8})\b", re.I)
_TECHNICIAN_DEPTH = re.compile(
    r"\b("
    r"what should i check|how (?:do|should) i (?:test|diagnose|check)|"
    r"test\s*#\s*\d|service (?:mode|procedure)|technician|"
    r"door will not lock|won'?t lock|will not lock"
    r")\b",
    re.I,
)
_UNLOCK_EVIDENCE = re.compile(
    r"will not unlock|won'?t unlock|door will not unlock|add garment|"
    r"door locks when cycle|touch (?:start/)?pause|f5\s*e2|lock failure",
    re.I,
)
_WRONG_UNLOCK_POLARITY = re.compile(
    r"door won'?t lock|door will not lock|ensure that door is completely closed|"
    r"door not closed",
    re.I,
)
_DIAG_ENTRY_EVIDENCE = re.compile(
    r"Activating Service Diagnostic Mode|"
    r"Select any three \(3\) buttons|"
    r"wait 30 seconds before\s+activating Service Diagnostic",
    re.I,
)
_DIAG_PAUSE_ENUM = re.compile(
    r"Enumeration:\s*\d+.{0,80}Pauses the machine",
    re.I | re.S,
)
_OWNER_DOC_TYPES = frozenset(
    {
        "owners_manual",
        "quick_start_guide",
        "knowledge_article",
        "warranty",
        "cycle_guide",
        "installation_instructions",
        "dimension_guide",
    }
)


def is_bibliographic_query(query: str) -> bool:
    """Lookup intent: which document applies, not how to repair a symptom."""
    return bool(_BIBLIOGRAPHIC.search(query))


def is_installation_query(query: str) -> bool:
    """Symptoms that often trace to installation faults rather than components."""
    return bool(_INSTALLATION.search(query))


def requested_revision(query: str) -> str | None:
    """Revision letter when the query names a specific manual revision."""
    match = _REVISION.search(query)
    return match.group(1).upper() if match else None


def is_acu_led_query(query: str) -> bool:
    """Procedural intent about the ACU status/diagnostic LED, not drum light."""
    return bool(_ACU_LED.search(query))


def queried_publications(query: str) -> set[str]:
    """Publication numbers explicitly named as documents in the query.

    Whirlpool part numbers also look like ``W`` + 8 digits (e.g. W10804741).
    Those must not trigger publication filtering — only document references.
    """
    if re.search(r"\bpart\s*(?:number|#|no\.?)\b", query, re.I):
        return set()
    return {m.group(1).upper() for m in _PUBLICATION.finditer(query)}


def is_technician_depth_query(query: str) -> bool:
    """Technician / diagnostic intent — prefer service literature over consumer KB."""
    return bool(_TECHNICIAN_DEPTH.search(query))


@dataclass
class RankAudit:
    """Optional collector for retrieval observability (Langfuse)."""

    rejected: list[dict[str, Any]] = field(default_factory=list)
    ranked_sorted: list["RankedHit"] = field(default_factory=list)
    diversity_dropped: list[dict[str, Any]] = field(default_factory=list)


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


def _is_superseded_doc(doc: Document) -> bool:
    return any(rel.get("type") == "superseded_by" for rel in doc.relationships())


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
    audit: RankAudit | None = None,
    audience: str | None = None,
) -> list[RankedHit]:
    """Drop inapplicable docs; boost correcting / pointer literature and error-code matches."""
    from repair_assistant.retrieval.query_expand import (
        door_lock_polarity,
        is_mid_cycle_stop_query,
    )

    by_id = _doc_by_id(manifest)
    query_codes = {c.upper() for c in (query_error_codes or [])}
    bibliographic = is_bibliographic_query(query)
    installation = is_installation_query(query)
    ref_targets = _reference_targets(hits, by_id)
    rev_letter = requested_revision(query) if bibliographic else None
    acu_led = is_acu_led_query(query)
    named_pubs = queried_publications(query)
    technician = is_technician_depth_query(query)
    lock_polarity = door_lock_polarity(query)
    mid_cycle = is_mid_cycle_stop_query(query)
    prefer_owner = (audience or "").lower() == "owner"

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
            if audit is not None:
                audit.rejected.append(
                    {
                        "doc_id": doc_id,
                        "chunk_id": hit["chunk_id"],
                        "page": hit.get("page"),
                        "score": round(float(hit["score"]), 4),
                        "publication_number": hit.get("publication_number"),
                        "revision": hit.get("revision"),
                        "apply_reason": reason,
                        "text_preview": " ".join((hit.get("text") or "").split())[:240],
                    }
                )
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
                # Prefer the current publication when a superseded twin also applies.
                if _is_superseded_doc(doc):
                    boost -= 0.25
            if doc.doc_type == "service_manual" and bibliographic:
                boost += 0.15
                rev = hit.get("revision")
                if rev_letter and rev and str(rev).upper() == rev_letter:
                    boost += 0.25
            if bibliographic and doc.doc_type in {
                "technical_service_pointer",
                "service_pointer",
            }:
                boost -= 0.12
                if rev_letter:
                    boost -= 0.18
            if doc.doc_type == "installation_instructions" and installation:
                boost += 0.12
            tier = (doc.data.get("authority") or {}).get("tier")
            if tier in {"service_literature", "service_pointer", "technical_service_pointer"}:
                boost += 0.02
            if technician and doc.doc_type in {"tech_sheet", "service_manual"}:
                boost += 0.30
            if technician and doc.doc_type == "knowledge_article":
                boost -= 0.45
            if prefer_owner and doc.doc_type in _OWNER_DOC_TYPES:
                boost += 0.12
            if prefer_owner and lock_polarity == "unlock" and doc.doc_type in {
                "owners_manual",
                "knowledge_article",
            }:
                boost += 0.10

        pub = hit.get("publication_number")
        if named_pubs:
            if pub and str(pub).upper() in named_pubs:
                boost += 0.45
            elif pub:
                # Query named a specific publication — demote near-duplicate twins.
                boost -= 0.35
        if ref_targets and pub and str(pub) in ref_targets:
            boost += 0.25
            if installation and query_codes:
                boost += 0.35
                if doc is not None and doc.doc_type == "installation_instructions":
                    boost += 0.15

        if acu_led:
            text = hit.get("text") or ""
            if re.search(r"drum light", text, re.I):
                boost -= 0.20
            if re.search(
                r"(status led|diagnostic led|step 10|0\.5.*0\.5|blinks? (rapidly|slowly))",
                text,
                re.I,
            ):
                boost += 0.30
            if re.search(r"TEST #1.*ACU Power Check", text, re.I):
                boost += 0.15

        text = hit.get("text") or ""
        if lock_polarity == "unlock":
            if _UNLOCK_EVIDENCE.search(text):
                boost += 0.28
            if _WRONG_UNLOCK_POLARITY.search(text) and not _UNLOCK_EVIDENCE.search(text):
                boost -= 0.22
        elif lock_polarity == "lock":
            if _WRONG_UNLOCK_POLARITY.search(text):
                boost += 0.12

        if mid_cycle:
            if _DIAG_ENTRY_EVIDENCE.search(text):
                boost += 0.38
            elif _DIAG_PAUSE_ENUM.search(text):
                # Pause-test enumeration rows are not "how to enter diagnostics".
                boost -= 0.20

        codes = [str(c).upper() for c in (hit.get("error_codes") or [])]
        kind = hit.get("kind") or ""
        if query_codes and query_codes.intersection(codes):
            # On installation-fault queries, keep KB/code recall but do not let
            # article boosts bury the referenced installation instructions.
            if installation and doc is not None and doc.doc_type == "knowledge_article":
                boost += 0.05
            elif technician and doc is not None and doc.doc_type == "knowledge_article":
                # Keep exact-code recall for KB, but without the depth boosts that
                # bury tech sheets on "what should I check?" questions.
                boost += 0.05
            else:
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

    # Query named a specific publication and we found it — drop near-duplicate
    # twins and unrelated pubs rather than relying on soft demotion alone.
    if named_pubs:
        matched = [
            h
            for h in ranked
            if h.publication_number and str(h.publication_number).upper() in named_pubs
        ]
        if matched:
            ranked = matched

    ranked.sort(key=lambda h: h.final_score, reverse=True)
    if audit is not None:
        audit.ranked_sorted = list(ranked)
    diverse = _diverse_top(ranked, limit, audit=audit)
    return prefer_owner_literature(diverse, manifest, audience=audience)


def prefer_owner_literature(
    ranked: list[RankedHit],
    manifest: Manifest,
    *,
    audience: str | None,
) -> list[RankedHit]:
    """For owner audience, restrict to owner-facing docs when any are available.

    Technician (and unset) audiences keep the full ranked list — no hard filter.
    If no applicable owner-facing hit exists, leave service literature in place
    ("where feasible").
    """
    if (audience or "").lower() != "owner" or not ranked:
        return ranked
    by_id = _doc_by_id(manifest)
    owner_hits = [
        hit
        for hit in ranked
        if (doc := by_id.get(hit.doc_id)) is not None and doc.doc_type in _OWNER_DOC_TYPES
    ]
    return owner_hits if owner_hits else ranked


def _diverse_top(
    ranked: list[RankedHit],
    limit: int,
    *,
    max_per_doc: int = 2,
    audit: RankAudit | None = None,
) -> list[RankedHit]:
    """Keep top scores while preventing one document from filling the entire window."""
    doc_ids = {h.doc_id for h in ranked}
    per_doc_cap = limit if len(doc_ids) == 1 else max_per_doc
    out: list[RankedHit] = []
    counts: dict[str, int] = {}
    for i, hit in enumerate(ranked):
        n = counts.get(hit.doc_id, 0)
        if n >= per_doc_cap:
            if audit is not None:
                audit.diversity_dropped.append(
                    {
                        "doc_id": hit.doc_id,
                        "chunk_id": hit.chunk_id,
                        "page": hit.page,
                        "final_score": round(hit.final_score, 4),
                        "reason": f"max_per_doc={per_doc_cap}",
                        "text_preview": " ".join(hit.text.split())[:240],
                    }
                )
            continue
        out.append(hit)
        counts[hit.doc_id] = n + 1
        if len(out) >= limit:
            if audit is not None:
                for rest in ranked[i + 1 :]:
                    audit.diversity_dropped.append(
                        {
                            "doc_id": rest.doc_id,
                            "chunk_id": rest.chunk_id,
                            "page": rest.page,
                            "final_score": round(rest.final_score, 4),
                            "reason": f"top_k={limit}",
                            "text_preview": " ".join(rest.text.split())[:240],
                        }
                    )
            break
    return out
