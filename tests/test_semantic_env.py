"""Semantic curator env: dedicated key, no ask-key fallback."""

from __future__ import annotations

import pytest

from repair_assistant.semantic import env as semantic_env


def test_semantic_openai_api_key_reads_dedicated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTIC_OPENAI_API_KEY", "sk-semantic-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ask-must-not-be-used")
    assert semantic_env.semantic_openai_api_key() == "sk-semantic-test"


def test_semantic_openai_api_key_does_not_fall_back_to_ask_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEMANTIC_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ask-only")
    with pytest.raises(RuntimeError, match="SEMANTIC_OPENAI_API_KEY"):
        semantic_env.semantic_openai_api_key()


def test_semantic_llm_base_url_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMANTIC_LLM_BASE_URL", raising=False)
    assert semantic_env.semantic_llm_base_url() is None
    monkeypatch.setenv("SEMANTIC_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    assert semantic_env.semantic_llm_base_url() == "http://127.0.0.1:1234/v1"
