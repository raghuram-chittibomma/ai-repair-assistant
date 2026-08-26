"""Unit tests for opt-in Langfuse tracing (no live Langfuse)."""

from __future__ import annotations

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
    fake_client.start_as_current_observation.return_value.__enter__.return_value = fake_span
    fake_client.start_as_current_observation.return_value.__exit__.return_value = None

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.observation("ask", input={"question": "hi"}, metadata={"m": 1}) as span:
            tracing.update_span(span, output={"abstained": False})
            assert span is fake_span

    fake_client.start_as_current_observation.assert_called_once()
    kwargs = fake_client.start_as_current_observation.call_args.kwargs
    assert kwargs["name"] == "ask"
    assert kwargs["as_type"] == "span"
    assert kwargs["metadata"]["m"] == 1
    fake_span.update.assert_called()
    fake_client.flush.assert_called_once()


def test_observation_merges_eval_trace_context(monkeypatch) -> None:
    from repair_assistant.observability.eval_context import eval_trace_context

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_as_current_observation.return_value.__enter__.return_value = fake_span
    fake_client.start_as_current_observation.return_value.__exit__.return_value = None

    with patch.object(tracing, "_client", return_value=fake_client):
        with eval_trace_context(
            eval_bench="qa",
            eval_run_id="20260101T000000Z",
            scenario_id="acu-led-step-10",
        ):
            with tracing.observation("ask", metadata={"audience": "owner"}):
                pass

    meta = fake_client.start_as_current_observation.call_args.kwargs["metadata"]
    assert meta["audience"] == "owner"
    assert meta["eval_bench"] == "qa"
    assert meta["eval_run_id"] == "20260101T000000Z"
    assert meta["scenario_id"] == "acu-led-step-10"


def test_child_observation_does_not_flush(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_as_current_observation.return_value.__enter__.return_value = fake_span
    fake_client.start_as_current_observation.return_value.__exit__.return_value = None

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.child_observation("retrieval", input={"query": "F5E2"}):
            pass

    fake_client.flush.assert_not_called()
    assert fake_client.start_as_current_observation.call_args.kwargs["name"] == "retrieval"


def test_generation_observation_uses_generation_type(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_as_current_observation.return_value.__enter__.return_value = fake_span
    fake_client.start_as_current_observation.return_value.__exit__.return_value = None

    with patch.object(tracing, "_client", return_value=fake_client):
        with tracing.generation("llm", model="gpt-4o-mini", input={"messages": []}):
            tracing.update_span(fake_span, output={"content": "hi"})

    kwargs = fake_client.start_as_current_observation.call_args.kwargs
    assert kwargs["as_type"] == "generation"
    assert kwargs["model"] == "gpt-4o-mini"
