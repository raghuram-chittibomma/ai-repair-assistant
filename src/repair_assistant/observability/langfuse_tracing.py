"""Opt-in Langfuse tracing (ADR-0018). No-op when keys are unset."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files
from repair_assistant.observability.eval_context import merge_eval_metadata
from repair_assistant.observability.redact import redact_for_trace

_DEFAULT_TRACE_MAX = 12_000
_log = logging.getLogger("repair_assistant.observability")
_synced_prompts: set[str] = set()

# Mutable span stack per thread — avoids ContextVar token reset errors when SSE
# generators yield/resume across asyncio context copies.
_tls = threading.local()
_langfuse_client: Any | None = None
_app_git_sha: str | None = None
_app_started_at: str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _NoOpSpan:
    """Stand-in when tracing is disabled."""

    def update(self, **kwargs: Any) -> None:
        return None


def tracing_enabled() -> bool:
    load_dotenv_files()
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    return bool(public and secret)


def app_started_at() -> str:
    """ISO timestamp when this process first loaded the tracing module."""
    return _app_started_at


def app_git_sha() -> str:
    """Full git SHA for this checkout (cached). Empty when git is unavailable.

    Uses the full object name (not ``--short``) so values like ``1472e98`` are
    never mistaken for scientific notation in OTEL/JSON metadata pipelines.
    """
    global _app_git_sha
    if _app_git_sha is not None:
        return _app_git_sha
    env_sha = os.environ.get("REPAIR_APP_GIT_SHA", "").strip()
    if env_sha:
        _app_git_sha = env_sha
        return _app_git_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = (out.stdout or "").strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        sha = ""
    _app_git_sha = sha
    return _app_git_sha


def build_stamp_metadata() -> dict[str, str]:
    """Metadata stamped on root observations (ADR-0023 stale-trace control)."""
    meta: dict[str, str] = {"app_started_at": app_started_at()}
    sha = app_git_sha()
    if sha:
        meta["app_git_sha"] = sha
    return meta


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


def prepare_trace_value(value: Any, *, max_chars: int | None = None) -> Any:
    """Truncate, then optionally redact serials (review R44)."""
    return redact_for_trace(truncate_for_trace(value, max_chars=max_chars))


def _span_ids(span: Any) -> tuple[str, str] | None:
    trace_id = getattr(span, "trace_id", None)
    span_id = getattr(span, "id", None)
    if trace_id and span_id:
        return str(trace_id), str(span_id)
    return None


def _trace_stack() -> list[tuple[str, str]]:
    stack = getattr(_tls, "trace_stack", None)
    if stack is None:
        stack = []
        _tls.trace_stack = stack
    return stack


def _clear_trace_stack() -> None:
    _tls.trace_stack = []


def _parent_trace_context() -> dict[str, str] | None:
    stack = _trace_stack()
    if not stack:
        return None
    trace_id, parent_span_id = stack[-1]
    return {"trace_id": trace_id, "parent_span_id": parent_span_id}


@contextmanager
def _push_span(span: Any) -> Iterator[None]:
    ids = _span_ids(span)
    if ids is None:
        yield
        return
    stack = _trace_stack()
    stack.append(ids)
    try:
        yield
    finally:
        if stack and stack[-1] == ids:
            stack.pop()


def _client() -> Any:
    """Return a singleton Langfuse client configured from the environment."""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    try:
        from langfuse import Langfuse
    except Exception as exc:  # pragma: no cover - depends on local Python/pydantic
        raise RuntimeError(
            "LANGFUSE_* keys are set but the langfuse package failed to import. "
            "Install with: pip install 'langfuse>=4,<5' "
            "(v4+ recommended on Python 3.14+)."
        ) from exc

    load_dotenv_files()
    _langfuse_client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"].strip(),
        secret_key=os.environ["LANGFUSE_SECRET_KEY"].strip(),
        host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000").strip()
        or "http://localhost:3000",
    )
    return _langfuse_client


def _start_observation(
    client: Any,
    *,
    name: str,
    as_type: str,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> Any:
    """Create a Langfuse observation without binding OTEL current context.

    ``start_as_current_observation`` attaches ContextVar tokens that break when
    SSE generators yield across asyncio context copies (``Failed to detach
    context``). Explicit ``trace_context`` + thread-local stack keep nesting.
    """
    trace_context = _parent_trace_context()
    kwargs: dict[str, Any] = {
        "name": name,
        "as_type": as_type,
        "input": prepare_trace_value(input) if input is not None else None,
        "metadata": prepare_trace_value(merge_eval_metadata(metadata)),
    }
    if trace_context is not None:
        kwargs["trace_context"] = trace_context
    if model is not None:
        kwargs["model"] = model
    return client.start_observation(**kwargs)


def _set_trace_session_id(span: Any, session_id: str) -> None:
    """Set Langfuse session.id on the underlying OTEL span (no context attach)."""
    otel = getattr(span, "_otel_span", None)
    if otel is None:
        return
    set_attr = getattr(otel, "set_attribute", None)
    if callable(set_attr):
        set_attr("session.id", session_id)


@contextmanager
def _managed_observation(
    client: Any,
    *,
    name: str,
    as_type: str,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
    session_id: str | None = None,
) -> Iterator[Any]:
    span = _start_observation(
        client,
        name=name,
        as_type=as_type,
        input=input,
        metadata=metadata,
        model=model,
    )
    if session_id:
        _set_trace_session_id(span, session_id)
    try:
        with _push_span(span):
            yield span
    finally:
        end = getattr(span, "end", None)
        if callable(end):
            end()


@contextmanager
def observation(
    name: str,
    *,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> Iterator[Any]:
    """Context manager for a root span. Yields a no-op when tracing is off."""
    if not tracing_enabled():
        yield _NoOpSpan()
        return

    merged_meta = merge_eval_metadata(metadata)
    merged_meta = {**build_stamp_metadata(), **merged_meta}
    if session_id:
        merged_meta = {**merged_meta, "diagnose_session_id": session_id}

    client = _client()
    _clear_trace_stack()
    try:
        with _managed_observation(
            client,
            name=name,
            as_type="span",
            input=input,
            metadata=merged_meta,
            session_id=session_id,
        ) as span:
            yield span
    finally:
        _clear_trace_stack()
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
    with _managed_observation(
        client,
        name=name,
        as_type=as_type,
        input=input,
        metadata=metadata,
    ) as span:
        yield span


def sync_prompt_file(name: str) -> None:
    """Best-effort snapshot of a git prompt file into Langfuse (ADR-0030).

    Files remain the source of truth. Failures never break ask/diagnose.
    """
    if not tracing_enabled() or name in _synced_prompts:
        return
    from repair_assistant.prompts import load_prompt

    text = load_prompt(name)
    try:
        client = _client()
        getter = getattr(client, "get_prompt", None)
        current = None
        if callable(getter):
            try:
                current = getter(name)
            except Exception:  # noqa: BLE001 — missing prompt is the create path
                current = None
        existing = getattr(current, "prompt", None) if current is not None else None
        if existing == text:
            _synced_prompts.add(name)
            return
        creator = getattr(client, "create_prompt", None)
        if callable(creator):
            creator(name=name, prompt=text, type="text", labels=["production"])
        _synced_prompts.add(name)
    except Exception:  # noqa: BLE001 — tracing must not fail the product path
        _log.warning("Langfuse prompt sync failed for %s", name, exc_info=True)


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
    with _managed_observation(
        client,
        name=name,
        as_type="generation",
        input=input,
        metadata=metadata,
        model=model,
    ) as span:
        yield span


def usage_from_openai(response: Any) -> dict[str, int] | None:
    """Map an OpenAI usage object onto Langfuse ``usage_details`` (review R43)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    total = getattr(usage, "total_tokens", None)
    if prompt is None and completion is None and total is None:
        return None
    details: dict[str, int] = {}
    if prompt is not None:
        details["input"] = int(prompt)
    if completion is not None:
        details["output"] = int(completion)
    if total is not None:
        details["total"] = int(total)
    elif details:
        details["total"] = details.get("input", 0) + details.get("output", 0)
    return details


def update_span(span: Any, **kwargs: Any) -> None:
    """Best-effort span.update (no-op span ignores). Truncates input/output."""
    update = getattr(span, "update", None)
    if not callable(update):
        return
    payload = dict(kwargs)
    if "input" in payload:
        payload["input"] = prepare_trace_value(payload["input"])
    if "output" in payload:
        payload["output"] = prepare_trace_value(payload["output"])
    if "metadata" in payload:
        payload["metadata"] = prepare_trace_value(payload["metadata"])
    usage = payload.pop("usage", None)
    if usage:
        payload["usage_details"] = usage
    update(**payload)


__all__ = [
    "app_git_sha",
    "app_started_at",
    "build_stamp_metadata",
    "child_observation",
    "generation",
    "observation",
    "prepare_trace_value",
    "trace_max_chars",
    "truncate_for_trace",
    "sync_prompt_file",
    "tracing_enabled",
    "update_span",
    "usage_from_openai",
]
