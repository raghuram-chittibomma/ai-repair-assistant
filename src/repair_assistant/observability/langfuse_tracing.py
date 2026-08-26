"""Opt-in Langfuse tracing (ADR-0018). No-op when keys are unset."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files
from repair_assistant.observability.eval_context import merge_eval_metadata

_DEFAULT_TRACE_MAX = 12_000


class _NoOpSpan:
    """Stand-in when tracing is disabled."""

    def update(self, **kwargs: Any) -> None:
        return None


def tracing_enabled() -> bool:
    load_dotenv_files()
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    return bool(public and secret)


def trace_max_chars() -> int:
    raw = os.environ.get("REPAIR_TRACE_MAX_CHARS", "").strip()
    if not raw:
        return _DEFAULT_TRACE_MAX
    try:
        return max(500, int(raw))
    except ValueError:
        return _DEFAULT_TRACE_MAX


def truncate_for_trace(value: Any, *, max_chars: int | None = None) -> Any:
    """Truncate long strings in trace payloads; recurse into dicts/lists."""
    limit = max_chars if max_chars is not None else trace_max_chars()
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[: limit - 20] + f"... [{len(value)} chars total]"
    if isinstance(value, dict):
        return {k: truncate_for_trace(v, max_chars=limit) for k, v in value.items()}
    if isinstance(value, list):
        return [truncate_for_trace(v, max_chars=limit) for v in value]
    return value


def _client() -> Any:
    """Return a process-local Langfuse client configured from the environment."""
    try:
        from langfuse import Langfuse
    except Exception as exc:  # pragma: no cover - depends on local Python/pydantic
        raise RuntimeError(
            "LANGFUSE_* keys are set but the langfuse package failed to import. "
            "Install with: pip install 'langfuse>=4,<5' "
            "(v4+ recommended on Python 3.14+)."
        ) from exc

    load_dotenv_files()
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"].strip(),
        secret_key=os.environ["LANGFUSE_SECRET_KEY"].strip(),
        host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000").strip()
        or "http://localhost:3000",
    )


@contextmanager
def observation(
    name: str,
    *,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Context manager for a root span. Yields a no-op when tracing is off."""
    if not tracing_enabled():
        yield _NoOpSpan()
        return

    client = _client()
    with client.start_as_current_observation(
        as_type="span",
        name=name,
        input=truncate_for_trace(input) if input is not None else None,
        metadata=merge_eval_metadata(metadata),
    ) as span:
        yield span
    client.flush()


@contextmanager
def child_observation(
    name: str,
    *,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    as_type: str = "span",
) -> Iterator[Any]:
    """Nested span/generation under the current trace. Does not flush."""
    if not tracing_enabled():
        yield _NoOpSpan()
        return

    client = _client()
    with client.start_as_current_observation(
        as_type=as_type,
        name=name,
        input=truncate_for_trace(input) if input is not None else None,
        metadata=merge_eval_metadata(metadata),
    ) as span:
        yield span


@contextmanager
def generation(
    name: str,
    *,
    model: str,
    input: Any,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Langfuse generation observation for an LLM call."""
    if not tracing_enabled():
        yield _NoOpSpan()
        return

    client = _client()
    with client.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=truncate_for_trace(input),
        metadata=merge_eval_metadata(metadata),
    ) as span:
        yield span


def update_span(span: Any, **kwargs: Any) -> None:
    """Best-effort span.update (no-op span ignores). Truncates input/output."""
    update = getattr(span, "update", None)
    if not callable(update):
        return
    payload = dict(kwargs)
    if "input" in payload:
        payload["input"] = truncate_for_trace(payload["input"])
    if "output" in payload:
        payload["output"] = truncate_for_trace(payload["output"])
    update(**payload)


__all__ = [
    "child_observation",
    "generation",
    "observation",
    "trace_max_chars",
    "truncate_for_trace",
    "tracing_enabled",
    "update_span",
]
