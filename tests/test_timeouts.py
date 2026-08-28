"""Tests for Phase 10 DB pool and LLM timeouts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from openai import APITimeoutError

from repair_assistant.api.db_pool import DatabasePool, PoolTimeoutError
from repair_assistant.qa.env import llm_timeout_seconds
from repair_assistant.qa.generate import LLMTimeoutError, OpenAIClient


def test_pool_acquire_times_out_when_exhausted() -> None:
    pool = DatabasePool("postgresql://unused", size=1, timeout_seconds=0.05)
    fake = MagicMock()
    fake.commit = MagicMock()
    fake.close = MagicMock()
    with patch.object(pool, "_create", return_value=fake):
        with pool.connection() as held:
            assert held is fake
            with pytest.raises(PoolTimeoutError, match="exhausted"), pool.connection():
                pass
        # After release, acquire succeeds again
        with pool.connection() as again:
            assert again is fake
    pool.close()


def test_openai_client_maps_api_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    client = OpenAIClient(api_key="sk-test", model="gpt-test", timeout=12.0)

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())

    with patch("openai.OpenAI", return_value=mock_openai):
        with pytest.raises(LLMTimeoutError, match="12"):
            client.complete("sys", "user")


def test_llm_timeout_seconds_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    assert llm_timeout_seconds() == 120.0
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    assert llm_timeout_seconds() == 45.0
