"""Whirlpool-style fault code tokens (F5E2), including spaced MindTouch forms (F5 E2)."""

from __future__ import annotations

import re

_TIGHT = re.compile(r"\b(F\dE\d)\b", re.IGNORECASE)
# Product-help titles often insert spaces: "F5 E2 - Error Code"
_LOOSE = re.compile(r"\bF\s*(\d)\s*E\s*(\d)\b", re.IGNORECASE)


def extract_error_codes(text: str) -> list[str]:
    """Return normalised codes like F5E2 found in ``text``."""
    found: set[str] = set()
    for match in _TIGHT.finditer(text):
        found.add(match.group(1).upper())
    for match in _LOOSE.finditer(text):
        found.add(f"F{match.group(1)}E{match.group(2)}".upper())
    return sorted(found)


def code_to_spaced_regex(code: str) -> str:
    """F5E2 → PostgreSQL regex matching F5E2 or F5 E2 / F 5 E 2."""
    code = code.strip().upper()
    if not re.fullmatch(r"F\dE\d", code):
        raise ValueError(f"not an F#E# code: {code!r}")
    return rf"F\s*{code[1]}\s*E\s*{code[3]}"
