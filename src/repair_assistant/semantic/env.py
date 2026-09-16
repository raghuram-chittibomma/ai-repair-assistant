"""Settings for the semantic curator step (ADR-0048).

Read only by ``repair-corpus segment`` and the review API. ``parse`` and
``ingest`` never import this module, so they still run without an OpenAI key
([ADR-0009](../../docs/adr/0009-local-open-embeddings.md) decision 3 as narrowed
by ADR-0048).

Curator billing uses ``SEMANTIC_OPENAI_API_KEY``, not ``OPENAI_API_KEY``, so
ask/diagnose spend stays on a separate project/key.
"""

from __future__ import annotations

import os

from repair_assistant.ingest.env import load_dotenv_files

#: Max pages per native-PDF / vision segmentation window (ADR-0049).
DEFAULT_SEGMENT_WINDOW_PAGES = 40
#: Legacy char budget (unused by PDF-native path; kept for env compatibility).
DEFAULT_SEGMENT_WINDOW_CHARS = 24_000
DEFAULT_ANCHOR_PREVIEW_CHARS = 400
#: Attempts at a representation that fits the embedder budget before the unit is
#: handed to a reviewer as over-limit (ADR-0048 decision 5).
DEFAULT_REPRESENTATION_ATTEMPTS = 2


def semantic_openai_api_key() -> str:
    """API key for propose / representation generation. No ask-key fallback."""
    load_dotenv_files()
    key = os.environ.get("SEMANTIC_OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "SEMANTIC_OPENAI_API_KEY is required for semantic propose/approve. "
            "Set it in .env.local (separate from OPENAI_API_KEY for cost tracking)."
        )
    return key


def semantic_llm_base_url() -> str | None:
    """Optional OpenAI-compatible base URL (local LLM later). Empty = default."""
    load_dotenv_files()
    url = os.environ.get("SEMANTIC_LLM_BASE_URL", "").strip()
    return url or None


def semantic_llm_model() -> str:
    """Segmentation model. ``SEMANTIC_LLM_MODEL`` wins, else ``LLM_MODEL``."""
    from repair_assistant.qa.env import llm_model

    load_dotenv_files()
    explicit = os.environ.get("SEMANTIC_LLM_MODEL", "").strip()
    return explicit or llm_model()


def _int_env(name: str, default: int) -> int:
    load_dotenv_files()
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def segment_window_chars() -> int:
    return _int_env("SEMANTIC_SEGMENT_WINDOW_CHARS", DEFAULT_SEGMENT_WINDOW_CHARS)


def segment_window_pages() -> int:
    return _int_env("SEMANTIC_SEGMENT_WINDOW_PAGES", DEFAULT_SEGMENT_WINDOW_PAGES)


def anchor_preview_chars() -> int:
    return _int_env("SEMANTIC_ANCHOR_PREVIEW_CHARS", DEFAULT_ANCHOR_PREVIEW_CHARS)


def representation_attempts() -> int:
    return _int_env(
        "SEMANTIC_REPRESENTATION_ATTEMPTS", DEFAULT_REPRESENTATION_ATTEMPTS
    )
