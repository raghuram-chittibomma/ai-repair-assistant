"""Unit tests for opt-in Langfuse tracing (no live Langfuse)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from repair_assistant.observability import langfuse_tracing as tracing


def test_tracing_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
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
    fake_span.update.assert_called()
    fake_client.flush.assert_called_once()
