"""Tests for fault-code normalisation (MindTouch spaced forms)."""

from repair_assistant.parsing.error_codes import code_to_spaced_regex, extract_error_codes


def test_extract_spaced_and_tight_codes() -> None:
    assert extract_error_codes("F5 E2 - Error Code") == ["F5E2"]
    assert extract_error_codes("codes F5E2 and F6E1") == ["F5E2", "F6E1"]


def test_spaced_regex() -> None:
    assert code_to_spaced_regex("F5E2") == r"F\s*5\s*E\s*2"
