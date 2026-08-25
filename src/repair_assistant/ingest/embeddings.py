"""Local open-source embeddings (no paid API). OpenAI is reserved for LLM inference."""

from __future__ import annotations

from typing import Protocol, Sequence

# Default: MIT-licensed, strong English retrieval, runs fully offline after download.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_EMBEDDING_DIMS = 768


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
