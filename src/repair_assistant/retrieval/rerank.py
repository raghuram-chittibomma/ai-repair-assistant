"""Cross-encoder rerank for the retrieval bake-off (ADR-0027 / review R14).

Not used by production ``search()``. Lazy-loads weights on first predict.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files

DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"
_TEXT_CHARS = 1500

_lock = threading.Lock()
_model: Any = None
_model_name: str | None = None


def rerank_model_name() -> str:
    load_dotenv_files()
    return os.environ.get("REPAIR_RERANK_MODEL", DEFAULT_RERANK_MODEL).strip() or (
        DEFAULT_RERANK_MODEL
    )


def _cross_encoder(model_name: str) -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def predict_pairs(
    pairs: Sequence[tuple[str, str]],
    *,
    model_name: str | None = None,
) -> list[float]:
    """Relevance scores, one per (query, passage) pair. Higher is better."""
    global _model, _model_name
    resolved = model_name or rerank_model_name()
    with _lock:
        if _model is None or _model_name != resolved:
            _model = _cross_encoder(resolved)
            _model_name = resolved
        encoder = _model
    if not pairs:
        return []
    raw = encoder.predict(list(pairs), show_progress_bar=False)
    return [float(x) for x in raw]


def rerank_hits(
    query: str,
    hits: list[dict],
    *,
    limit: int,
    score_fn: Callable[[Sequence[tuple[str, str]]], Sequence[float]] | None = None,
) -> list[dict]:
    """Reorder hits by cross-encoder score and keep ``limit``."""
    if not hits:
        return []
    pairs = [(query, (hit.get("text") or "")[:_TEXT_CHARS]) for hit in hits]
    scores = list(score_fn(pairs) if score_fn is not None else predict_pairs(pairs))
    if len(scores) != len(hits):
        raise ValueError("rerank score_fn must return one score per hit")
    ordered = sorted(
        zip(hits, scores, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    out: list[dict] = []
    for hit, score in ordered[: max(1, limit)]:
        row = dict(hit)
        row["score"] = float(score)
        out.append(row)
    return out
