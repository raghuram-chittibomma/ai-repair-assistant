"""Serialize retrieval pipeline details for Langfuse spans."""

from __future__ import annotations

from typing import Any

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.retrieval.rank import RankAudit, RankedHit
from repair_assistant.retrieval.search import Hit

_TRACE_PREVIEW = 240


def _preview(text: str, *, max_len: int = _TRACE_PREVIEW) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


def hit_row(
    *,
    doc_id: str,
    chunk_id: str,
    page: int | None,
    score: float,
    final_score: float | None = None,
    publication_number: str | None = None,
    revision: str | None = None,
    kind: str | None = None,
    apply_reason: str = "",
    text: str = "",
    status: str = "selected",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "page": page,
        "score": round(score, 4),
        "status": status,
    }
    if final_score is not None:
        row["final_score"] = round(final_score, 4)
    if publication_number:
        row["publication_number"] = publication_number
    if revision:
        row["revision"] = revision
    if kind:
        row["kind"] = kind
    if apply_reason:
        row["apply_reason"] = apply_reason
    if text:
        row["text_preview"] = _preview(text)
    return row


def ranked_hit_row(hit: RankedHit, *, status: str = "selected") -> dict[str, Any]:
    return hit_row(
        doc_id=hit.doc_id,
        chunk_id=hit.chunk_id,
        page=hit.page,
        score=hit.score,
        final_score=hit.final_score,
        publication_number=hit.publication_number,
        revision=hit.revision,
        kind=hit.kind,
        apply_reason=hit.apply_reason,
        text=hit.text,
        status=status,
    )


def search_hit_row(hit: Hit, *, status: str = "selected") -> dict[str, Any]:
    return hit_row(
        doc_id=hit.doc_id,
        chunk_id=hit.chunk_id,
        page=hit.page,
        score=hit.score,
        final_score=hit.score,
        publication_number=hit.publication_number,
        revision=hit.revision,
        kind=hit.kind,
        apply_reason=hit.apply_reason,
        text=hit.text,
        status=status,
    )


def build_retrieval_trace_output(
    *,
    query: str,
    appliance: Appliance | None,
    limit: int,
    overfetch: int,
    source_counts: dict[str, int],
    merged_count: int,
    audit: RankAudit | None,
    final_hits: list[Hit],
    bibliographic: bool,
    revision_query: str | None,
) -> dict[str, Any]:
    """Structured retrieval audit for Langfuse ``retrieval`` span output."""
    appliance_out: dict[str, Any] | None = None
    if appliance is not None:
        appliance_out = {"model": appliance.model}
        if appliance.serial:
            appliance_out["serial"] = appliance.serial

    out: dict[str, Any] = {
        "query": query,
        "appliance": appliance_out,
        "limit": limit,
        "overfetch": overfetch,
        "bibliographic": bibliographic,
        "revision_query": revision_query,
        "sources": source_counts,
        "merged_candidates": merged_count,
        "selected_count": len(final_hits),
        "selected": [search_hit_row(h) for h in final_hits],
    }

    if audit is None:
        return out

    out["rejected_applicability"] = list(audit.rejected)
    out["ranked_before_diversity"] = [ranked_hit_row(h) for h in audit.ranked_sorted]
    out["diversity_dropped"] = list(audit.diversity_dropped)
    out["filtered_out_count"] = len(audit.rejected) + len(audit.diversity_dropped)
    return out


__all__ = [
    "build_retrieval_trace_output",
    "hit_row",
    "ranked_hit_row",
    "search_hit_row",
]
