"""Stamps that make a scorecard regenerable (review R37)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from repair_assistant.ingest.env import embedding_model, project_root
from repair_assistant.qa.env import llm_model

_LOCKFILE_NAME = "uv.lock"


def lockfile_path() -> Path | None:
    path = project_root() / _LOCKFILE_NAME
    return path if path.is_file() else None


def lockfile_stamp() -> str:
    """Short content hash of the committed lockfile, or `none`."""
    path = lockfile_path()
    if path is None:
        return "none"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{_LOCKFILE_NAME}@{digest}"


def scorecard_repro_lines() -> list[str]:
    """Header lines stamped onto every bench scorecard."""
    return [
        f"- Lockfile: `{lockfile_stamp()}`",
        f"- LLM_MODEL: `{llm_model()}`",
        f"- EMBEDDING_MODEL: `{embedding_model()}`",
    ]
