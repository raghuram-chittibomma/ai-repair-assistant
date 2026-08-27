"""OpenAI settings for grounded Q&A (charter: paid inference only)."""

from __future__ import annotations

import os

from repair_assistant.ingest.env import load_dotenv_files

DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0


def openai_api_key() -> str:
    load_dotenv_files()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for repair-corpus ask. Set it in .env.local."
        )
    return key


def llm_model() -> str:
    load_dotenv_files()
    return os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL).strip()


def llm_timeout_seconds() -> float:
    """OpenAI request timeout (complete + stream). Override with LLM_TIMEOUT_SECONDS."""
    load_dotenv_files()
    raw = os.environ.get("LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"LLM_TIMEOUT_SECONDS must be a number (got {raw!r})"
        ) from exc
    if value <= 0:
        raise RuntimeError("LLM_TIMEOUT_SECONDS must be positive")
    return value
