"""Embedder token budget for retrieval representations (ADR-0048 decision 5).

``BAAI/bge-base-en-v1.5`` accepts 512 tokens and ``sentence-transformers``
truncates anything longer without complaint. A representation that does not fit
is therefore not a smaller representation, it is a silently incomplete one, so
this module exists to make the overflow visible before it reaches pgvector.

The real tokenizer is used when it can be loaded. When it cannot — CI never
downloads BGE — a deliberately pessimistic estimate stands in, so the fallback
errs towards rejecting a representation that would have fitted rather than
accepting one that would have been truncated.
"""

from __future__ import annotations

import re
import threading

#: Hard model limit. Includes the [CLS] and [SEP] positions.
BGE_MAX_TOKENS = 512
#: Budget offered to a representation. The headroom absorbs the difference
#: between the estimate and the real tokenizer on unusual strings.
DEFAULT_TOKEN_BUDGET = 480

_WORD = re.compile(r"\w+|[^\w\s]")

_lock = threading.Lock()
_tokenizer: object | None = None
_tokenizer_tried = False


def _load_tokenizer() -> object | None:
    """The real BGE tokenizer, or None when transformers/weights are absent."""
    global _tokenizer, _tokenizer_tried
    with _lock:
        if _tokenizer_tried:
            return _tokenizer
        _tokenizer_tried = True
        try:
            from transformers import AutoTokenizer

            from repair_assistant.ingest.env import embedding_model

            model = embedding_model()
            if not model or model == "none":
                return None
            _tokenizer = AutoTokenizer.from_pretrained(model)
        except Exception:  # noqa: BLE001 — any failure falls back to the estimate
            _tokenizer = None
        return _tokenizer


def reset_tokenizer_cache() -> None:
    """Test helper: forget whether the tokenizer could be loaded."""
    global _tokenizer, _tokenizer_tried
    with _lock:
        _tokenizer = None
        _tokenizer_tried = False


def estimate_tokens(text: str) -> int:
    """Pessimistic WordPiece estimate used when the tokenizer is unavailable.

    WordPiece splits unknown and compound tokens into several pieces, which is
    exactly what appliance part numbers and codes are. Counting each word or
    punctuation mark and charging long or digit-bearing words extra keeps the
    estimate at or above the real count for this corpus.
    """
    pieces = _WORD.findall(text or "")
    total = 2  # [CLS] / [SEP]
    for piece in pieces:
        if len(piece) <= 4:
            total += 1
        elif any(ch.isdigit() for ch in piece):
            # W11169652, F6E1, CN4-12 all fragment heavily.
            total += max(2, (len(piece) + 2) // 3)
        else:
            total += max(1, (len(piece) + 3) // 4)
    return total


def count_tokens(text: str) -> int:
    """Token count for the configured embedder, real where possible."""
    tokenizer = _load_tokenizer()
    if tokenizer is not None:
        try:
            encoded = tokenizer(text or "", add_special_tokens=True)
            return len(encoded["input_ids"])
        except Exception:  # noqa: BLE001 — fall back rather than fail a review
            pass
    return estimate_tokens(text)


def tokenizer_is_exact() -> bool:
    """True when counts come from the model's own tokenizer."""
    return _load_tokenizer() is not None


def fits(text: str, *, budget: int = DEFAULT_TOKEN_BUDGET) -> bool:
    return count_tokens(text) <= budget


def overflow(text: str, *, budget: int = DEFAULT_TOKEN_BUDGET) -> int:
    """Tokens over budget; zero when the text fits."""
    return max(0, count_tokens(text) - budget)
