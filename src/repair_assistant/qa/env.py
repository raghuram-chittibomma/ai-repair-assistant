"""OpenAI settings for grounded Q&A (charter: paid inference only)."""

from __future__ import annotations

import os

from repair_assistant.ingest.env import load_dotenv_files

DEFAULT_LLM_MODEL = "gpt-4o-mini"


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
