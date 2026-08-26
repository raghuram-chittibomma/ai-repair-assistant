"""Opt-in Langfuse tracing (ADR-0018). No-op when keys are unset."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files


class _NoOpSpan:
    """Stand-in when tracing is disabled."""

    def update(self, **kwargs: Any) -> None:
        return None


def tracing_enabled() -> bool:
    load_dotenv_files()
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    return bool(public and secret)


def _client() -> Any:
    """Return a Langfuse client configured from the environment."""
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
        input=input,
        metadata=metadata or {},
    ) as span:
        yield span
    client.flush()


def update_span(span: Any, **kwargs: Any) -> None:
    """Best-effort span.update (no-op span ignores)."""
    update = getattr(span, "update", None)
    if callable(update):
        update(**kwargs)


__all__ = [
    "observation",
    "tracing_enabled",
    "update_span",
]
