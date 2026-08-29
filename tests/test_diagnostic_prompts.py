"""Diagnose prompt helpers (review R25 transcript window)."""

from __future__ import annotations

from repair_assistant.diagnostic.prompts import window_transcript


def test_window_transcript_keeps_first_and_recent() -> None:
    lines = [f"User: turn {i}" for i in range(20)]
    text = window_transcript(lines, max_lines=6)
    assert text.startswith("User: turn 0")
    assert "earlier lines omitted" in text
    assert text.endswith("User: turn 19")
    assert "User: turn 2" not in text


def test_window_transcript_short_list_unchanged() -> None:
    lines = ["User: a", "Assistant: b"]
    assert window_transcript(lines) == "User: a\nAssistant: b"
