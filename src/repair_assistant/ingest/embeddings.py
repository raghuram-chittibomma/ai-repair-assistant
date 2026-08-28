"""Local open-source embeddings (no paid API). OpenAI is reserved for LLM inference."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

# Default: MIT-licensed, strong English retrieval, runs fully offline after download.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_EMBEDDING_DIMS = 768

_shared_lock = threading.Lock()
_shared_embedder: Embedder | None = None
_shared_model: str | None = None


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class NullEmbedder:
    """Leaves embeddings unset (NULL in Postgres)."""

    model = "none"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[] for _ in texts]


class LocalEmbedder:
    """sentence-transformers encode on the workstation (zero inference cost)."""

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = model
        # normalize_embeddings=True → cosine distance matches pgvector cosine ops.
        self._encoder = SentenceTransformer(model)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._encoder.encode(
            list(texts),
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [row.tolist() for row in vectors]


def build_embedder(*, skip: bool, model: str = DEFAULT_EMBEDDING_MODEL) -> Embedder:
    if skip:
        return NullEmbedder()
    return LocalEmbedder(model=model)


def get_shared_embedder(*, model: str | None = None) -> Embedder:
    """Process-wide LocalEmbedder (Phase 10). Avoids reloading BGE per request."""
    global _shared_embedder, _shared_model
    from repair_assistant.ingest.env import embedding_model

    resolved = model or embedding_model()
    with _shared_lock:
        if _shared_embedder is None or _shared_model != resolved:
            _shared_embedder = LocalEmbedder(model=resolved)
            _shared_model = resolved
        return _shared_embedder


def shared_embedder_loaded() -> bool:
    with _shared_lock:
        return _shared_embedder is not None


def reset_shared_embedder() -> None:
    """Test helper: drop the process singleton."""
    global _shared_embedder, _shared_model
    with _shared_lock:
        _shared_embedder = None
        _shared_model = None
