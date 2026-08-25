"""Load environment and resolve DATABASE_URL for ingestion."""

from __future__ import annotations

import os
from pathlib import Path

from repair_assistant.ingest.embeddings import (
    DEFAULT_EMBEDDING_DIMS,
    DEFAULT_EMBEDDING_MODEL,
)


def project_root() -> Path:
    # src/repair_assistant/ingest/env.py → repo root
    return Path(__file__).resolve().parents[3]


def load_dotenv_files(root: Path | None = None) -> None:
    """Load .env then .env.local if present (local overrides). No dependency on python-dotenv."""
    root = root or project_root()
    for name in (".env", ".env.local"):
        path = root / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Do not clobber variables already set in the process environment.
            if key and key not in os.environ:
                os.environ[key] = value


def database_url() -> str:
    load_dotenv_files()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or "DOCKER_HOST" in url:
        raise RuntimeError(
            "DATABASE_URL is missing or still contains the DOCKER_HOST placeholder. "
            "Copy .env.example to .env.local and set a real connection string "
            "(see docs/INFRASTRUCTURE.md)."
        )
    return url


def embedding_model() -> str:
    load_dotenv_files()
    return os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip()


def embedding_dims() -> int:
    load_dotenv_files()
    return int(os.environ.get("EMBEDDING_DIMS", str(DEFAULT_EMBEDDING_DIMS)))
