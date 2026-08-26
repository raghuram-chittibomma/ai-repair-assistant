"""Opt-in eval metadata for Langfuse spans (E11)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_EVAL_META: ContextVar[dict[str, Any] | None] = ContextVar("eval_meta", default=None)


@contextmanager
def eval_trace_context(
    *,
    eval_bench: str,
    eval_run_id: str,
    scenario_id: str | None = None,
) -> Iterator[None]:
    """Attach bench identifiers to Langfuse observation metadata for this scope."""
    payload: dict[str, Any] = {
        "eval_bench": eval_bench,
        "eval_run_id": eval_run_id,
    }
    if scenario_id is not None:
        payload["scenario_id"] = scenario_id
    token = _EVAL_META.set(payload)
    try:
        yield
    finally:
        _EVAL_META.reset(token)


def current_eval_metadata() -> dict[str, Any]:
    """Copy of active eval metadata (empty when not under a bench)."""
    return dict(_EVAL_META.get() or {})


def merge_eval_metadata(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge caller metadata with active eval context (eval keys win on clash)."""
    merged = dict(metadata or {})
    merged.update(current_eval_metadata())
    return merged
