"""Unit tests for semantic embed bake-off helpers (no live DB)."""

from repair_assistant.retrieval.semantic_embed_bench import window_source_text
from repair_assistant.semantic.tokens import DEFAULT_TOKEN_BUDGET, count_tokens


def test_window_source_text_fits_single_block() -> None:
    text = "Locate four transport bolts on rear of washer."
    windows = window_source_text(text, budget=DEFAULT_TOKEN_BUDGET)
    assert windows == [text]


def test_window_source_text_splits_long_body() -> None:
    paras = [f"Paragraph {i}: " + ("transport bolt drain hose " * 40) for i in range(12)]
    text = "\n\n".join(paras)
    assert count_tokens(text) > DEFAULT_TOKEN_BUDGET
    windows = window_source_text(text, budget=DEFAULT_TOKEN_BUDGET)
    assert len(windows) >= 2
    assert all(count_tokens(w) <= DEFAULT_TOKEN_BUDGET for w in windows)
    # Content preserved (paragraphs may be character-split when one overflows).
    joined = "\n".join(windows)
    for i in range(12):
        assert f"Paragraph {i}:" in joined
    assert "transport bolt" in joined
