"""Unit tests for opt-in Langfuse tracing (no live Langfuse)."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

from repair_assistant.observability import langfuse_tracing as tracing


def test_tracing_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # Ignore .env.local so a developer machine with keys set still passes.
    monkeypatch.setattr(tracing, "load_dotenv_files", lambda: None)
    assert tracing.tracing_enabled() is False
    with tracing.observation("ask", input={"q": "x"}) as span:
        tracing.update_span(span, output={"ok": True})
        assert isinstance(span, tracing._NoOpSpan)


def test_observation_uses_langfuse_when_keys_set(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    assert tracing.tracing_enabled() is True

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.observation("ask", input={"question": "hi"}, metadata={"m": 1}) as span:
            tracing.update_span(span, output={"abstained": False})
            assert span is fake_span

    fake_client.start_observation.assert_called_once()
    kwargs = fake_client.start_observation.call_args.kwargs
    assert kwargs["name"] == "ask"
    assert kwargs["as_type"] == "span"
    assert kwargs["metadata"]["m"] == 1
    fake_span.update.assert_called()
    fake_span.end.assert_called_once()
    fake_client.flush.assert_called_once()


def test_observation_merges_eval_trace_context(monkeypatch) -> None:
    from repair_assistant.observability.eval_context import eval_trace_context

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span

    with patch.object(tracing, "_client", return_value=fake_client), eval_trace_context(
        eval_bench="qa",
        eval_run_id="20260101T000000Z",
        scenario_id="acu-led-step-10",
    ), tracing.observation("ask", metadata={"audience": "owner"}):
        pass

    meta = fake_client.start_observation.call_args.kwargs["metadata"]
    assert meta["audience"] == "owner"
    assert meta["eval_bench"] == "qa"
    assert meta["eval_run_id"] == "20260101T000000Z"
    assert meta["scenario_id"] == "acu-led-step-10"


def test_observation_sets_session_id_on_otel_span(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_otel = MagicMock()
    fake_span = MagicMock()
    fake_span._otel_span = fake_otel
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span

    with patch.object(tracing, "_client", return_value=fake_client), tracing.observation(
        "diagnose",
        input={"message": "hi"},
        session_id="sess-abc",
    ) as span:
        assert span is fake_span

    fake_otel.set_attribute.assert_called_with("session.id", "sess-abc")
    meta = fake_client.start_observation.call_args.kwargs["metadata"]
    assert meta["diagnose_session_id"] == "sess-abc"


def test_child_observation_does_not_flush(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.child_observation("retrieval", input={"query": "F5E2"}):
            pass

    fake_client.flush.assert_not_called()
    assert fake_client.start_observation.call_args.kwargs["name"] == "retrieval"
    fake_span.end.assert_called_once()


def test_usage_from_openai_maps_token_counts() -> None:
    usage = MagicMock()
    usage.prompt_tokens = 12
    usage.completion_tokens = 4
    usage.total_tokens = 16
    response = MagicMock()
    response.usage = usage
    assert tracing.usage_from_openai(response) == {
        "input": 12,
        "output": 4,
        "total": 16,
    }
    assert tracing.usage_from_openai(MagicMock(usage=None)) is None


def test_update_span_passes_usage_details() -> None:
    span = MagicMock()
    tracing.update_span(
        span,
        output={"content": "hi"},
        usage={"input": 12, "output": 4, "total": 16},
    )
    kwargs = span.update.call_args.kwargs
    assert kwargs["usage_details"] == {"input": 12, "output": 4, "total": 16}
    assert "usage" not in kwargs


def test_generation_observation_uses_generation_type(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.generation("llm", model="gpt-4o-mini", input={"messages": []}):
            tracing.update_span(fake_span, output={"content": "hi"})

    kwargs = fake_client.start_observation.call_args.kwargs
    assert kwargs["as_type"] == "generation"
    assert kwargs["model"] == "gpt-4o-mini"


def test_child_observation_passes_trace_context_under_root(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    root_span = MagicMock()
    root_span.trace_id = "trace-root"
    root_span.id = "span-root"
    child_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.side_effect = [root_span, child_span]

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.observation("ask", input={"question": "door"}):
            with tracing.child_observation("retrieval", input={"query": "door"}):
                pass

    child_kwargs = fake_client.start_observation.call_args_list[1].kwargs
    assert child_kwargs["trace_context"] == {
        "trace_id": "trace-root",
        "parent_span_id": "span-root",
    }


def test_trace_context_survives_generator_yield(monkeypatch) -> None:
    """Streaming ask yields before retrieval; explicit trace stack must still nest."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    root_span = MagicMock()
    root_span.trace_id = "trace-stream"
    root_span.id = "span-stream"
    child_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.side_effect = [root_span, child_span]

    def stream_like_ask():
        with tracing.observation("ask", input={"stream": True}):
            yield "status"
            with tracing.child_observation("retrieval"):
                pass

    gen = stream_like_ask()
    with patch.object(tracing, "_client", return_value=fake_client):
        next(gen)
        with contextlib.suppress(StopIteration):
            gen.send(None)

    child_kwargs = fake_client.start_observation.call_args_list[1].kwargs
    assert child_kwargs["trace_context"] == {
        "trace_id": "trace-stream",
        "parent_span_id": "span-stream",
    }
