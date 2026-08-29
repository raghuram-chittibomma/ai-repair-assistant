"""OpenAI settings for grounded Q&A (charter: paid inference only)."""

from __future__ import annotations

import os

from repair_assistant.ingest.env import load_dotenv_files

#: Dated snapshot, not the floating `gpt-4o-mini` alias (review R37).
DEFAULT_LLM_MODEL = "gpt-4o-mini-2024-07-18"
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
#: Total attempts, not retries: 3 means one call plus two retries.
DEFAULT_LLM_MAX_ATTEMPTS = 3
DEFAULT_LLM_RETRY_BASE_SECONDS = 0.5
#: Bound completion length (review R25). Transcript windowing is a later slice.
DEFAULT_LLM_MAX_TOKENS = 2048


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


def llm_max_attempts() -> int:
    """Total attempts for a transient LLM failure. Override with LLM_MAX_ATTEMPTS.

    Timeouts are deliberately excluded from retry: the timeout is already the
    latency bound, so retrying one triples the worst case a caller waits.
    """
    load_dotenv_files()
    raw = os.environ.get("LLM_MAX_ATTEMPTS", "").strip()
    if not raw:
        return DEFAULT_LLM_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LLM_MAX_ATTEMPTS
    return max(1, value)


def llm_retry_base_seconds() -> float:
    """Base delay for exponential backoff. Override with LLM_RETRY_BASE_SECONDS."""
    load_dotenv_files()
    raw = os.environ.get("LLM_RETRY_BASE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_LLM_RETRY_BASE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LLM_RETRY_BASE_SECONDS
    return value if value >= 0 else DEFAULT_LLM_RETRY_BASE_SECONDS


def llm_max_tokens() -> int:
    """Cap on generated tokens. Override with LLM_MAX_TOKENS."""
    load_dotenv_files()
    raw = os.environ.get("LLM_MAX_TOKENS", "").strip()
    if not raw:
        return DEFAULT_LLM_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LLM_MAX_TOKENS
    return value if value > 0 else DEFAULT_LLM_MAX_TOKENS
