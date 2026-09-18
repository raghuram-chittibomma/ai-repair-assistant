"""Pre-LLM weak-evidence pack gate (ADR-0052).

Abstain when top‑K is only weak vector similarity and no high-precision arm
hit is present. Exact code / connector / named-pub / revision recalls are
exempt so stamped scores are not killed by a cosine floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repair_assistant.parsing.error_codes import extract_connector_ids, extract_error_codes
from repair_assistant.retrieval.rank import (
    is_bibliographic_query,
    queried_publications,
    requested_revision,
)

#: code_fetch / connector seed stamps use 1.0.
_EXACT_ARM_SCORE = 0.999


@dataclass(frozen=True)
class WeakEvidenceAssessment:
    """Result of the weak-pack check (also stamped on Langfuse)."""

    weak: bool
    top_score: float | None
    threshold: float | None
    precision_exempt: bool

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "weak_evidence_gate": "abstain" if self.weak else "pass",
            "top_vector_score": self.top_score,
            "threshold": self.threshold,
            "precision_exempt": self.precision_exempt,
        }


def _hit_score(hit: Any) -> float:
    if isinstance(hit, dict):
        return float(hit.get("score") or 0.0)
    return float(getattr(hit, "score", 0.0) or 0.0)


def _hit_text(hit: Any) -> str:
    if isinstance(hit, dict):
        return str(hit.get("text") or "")
    return str(getattr(hit, "text", "") or "")


def _hit_error_codes(hit: Any) -> list[str]:
    raw = hit.get("error_codes") if isinstance(hit, dict) else getattr(hit, "error_codes", None)
    return [str(c) for c in (raw or [])]


def _hit_publication(hit: Any) -> str | None:
    pub = (
        hit.get("publication_number")
        if isinstance(hit, dict)
        else getattr(hit, "publication_number", None)
    )
    return str(pub).upper() if pub else None


def _hit_revision(hit: Any) -> str | None:
    rev = hit.get("revision") if isinstance(hit, dict) else getattr(hit, "revision", None)
    return str(rev).upper() if rev else None


def is_high_precision_hit(hit: Any, query: str) -> bool:
    """True when the hit is (or matches) a high-precision retrieval arm."""
    if _hit_score(hit) >= _EXACT_ARM_SCORE:
        return True

    q = query or ""
    codes = {c.upper() for c in extract_error_codes(q)}
    if codes:
        hit_codes = {c.upper() for c in _hit_error_codes(hit)}
        if codes & hit_codes:
            return True

    connectors = extract_connector_ids(q)
    if connectors:
        text_u = _hit_text(hit).upper()
        if any(c.upper() in text_u for c in connectors):
            return True

    named = queried_publications(q)
    pub = _hit_publication(hit)
    if named and pub and pub in named:
        return True

    rev = requested_revision(q)
    hit_rev = _hit_revision(hit)
    return bool(
        rev and hit_rev and hit_rev == rev.upper() and is_bibliographic_query(q)
    )


def assess_weak_evidence_pack(
    hits: list[Any],
    *,
    query: str = "",
    min_score: float | None = None,
) -> WeakEvidenceAssessment:
    """Return whether the selected pack is too weak to send to the answer LLM.

    ``min_score`` None or ``<= 0`` disables the gate (default until calibrated).
    Empty packs are not weak here — callers already map those to
    ``ABSTAIN_NO_EVIDENCE``.
    """
    if min_score is None or min_score <= 0:
        return WeakEvidenceAssessment(
            weak=False,
            top_score=None,
            threshold=None,
            precision_exempt=False,
        )
    if not hits:
        return WeakEvidenceAssessment(
            weak=False,
            top_score=None,
            threshold=float(min_score),
            precision_exempt=False,
        )

    precision = any(is_high_precision_hit(h, query) for h in hits)
    top = max(_hit_score(h) for h in hits)
    if precision:
        return WeakEvidenceAssessment(
            weak=False,
            top_score=top,
            threshold=float(min_score),
            precision_exempt=True,
        )
    return WeakEvidenceAssessment(
        weak=top < float(min_score),
        top_score=top,
        threshold=float(min_score),
        precision_exempt=False,
    )


def is_weak_evidence_pack(
    hits: list[Any],
    *,
    query: str = "",
    min_score: float | None = None,
) -> bool:
    """Convenience wrapper around :func:`assess_weak_evidence_pack`."""
    return assess_weak_evidence_pack(hits, query=query, min_score=min_score).weak


__all__ = [
    "WeakEvidenceAssessment",
    "assess_weak_evidence_pack",
    "is_high_precision_hit",
    "is_weak_evidence_pack",
]
