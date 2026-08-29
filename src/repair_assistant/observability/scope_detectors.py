"""Cheap detectors for ADR-0025 deferral triggers."""

from __future__ import annotations

import os

CURATION_DOCUMENT_THRESHOLD = 50


def configured_worker_count() -> int:
    """How many API processes the operator asked for (default 1)."""
    for name in ("REPAIR_API_WORKERS", "WEB_CONCURRENCY"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            return max(1, int(raw))
        except ValueError:
            continue
    return 1


def worker_count_warning(workers: int | None = None) -> str | None:
    """Sessions are process-local; more than one worker partitions them (R32)."""
    count = configured_worker_count() if workers is None else workers
    if count <= 1:
        return None
    return (
        f"REPAIR_API_WORKERS={count}: diagnose sessions are in-process memory. "
        "More than one worker silently partitions them (ADR-0025 / R32)."
    )


def curation_scale_notice(
    document_count: int,
    *,
    threshold: int = CURATION_DOCUMENT_THRESHOLD,
) -> str | None:
    """Announce R47's reopen trigger when the manifest grows past ~50 docs."""
    if document_count <= threshold:
        return None
    return (
        f"Notice (ADR-0025 / R47): manifest has {document_count} documents "
        f"(threshold {threshold}). Curation tooling was deferred; reopen that "
        "ADR if a second brand is added or hand-authoring is the bottleneck."
    )
