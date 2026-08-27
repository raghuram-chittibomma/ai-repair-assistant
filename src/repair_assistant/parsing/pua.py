"""Map Whirlpool tech-sheet private-use glyphs to list structure.

Tech sheets render procedure bullets with Wingdings positions in the Unicode
private use area (notably U+F0D8 and U+F06E). Naive extractors leave those
codepoints in place; a parser that does not map them loses list boundaries.
"""

from __future__ import annotations

import re
from typing import Any

# Observed on W11156989A / W11320651B. Values are the structural meaning we
# assign, not a claim about Wingdings' public mapping table.
PUA_LIST_MARKERS: dict[str, str] = {
    "\uf0d8": "•",  # filled bullet used for procedure steps
    "\uf06e": "•",  # alternate bullet / checkbox-like marker in fault tables
}

_PUA_RE = re.compile("[\ue000-\uf8ff]")

# pdfplumber merges overdrawn strip-circuit labels (J36-1 drawn atop J6-1)
# into interleaves like JJ366--11. Collapse back to the longer connector id.
_OVERDRAWN_J = re.compile(r"J{2}(\d)(\d)\2")
_OVERDRAWN_PIN = re.compile(r"-{2}(\d)\1\b")


def collapse_overdrawn_connector_labels(text: str) -> str:
    """Undo pdfplumber overdraw merges: ``JJ366--11`` → ``J36-1``."""
    text = _OVERDRAWN_J.sub(r"J\1\2", text)
    text = _OVERDRAWN_PIN.sub(r"-\1", text)
    return text


def map_pua(text: str, *, replace_unknown: str = "") -> str:
    """Replace known PUA list markers; drop or replace other PUA codepoints."""

    def _sub(match: re.Match[str]) -> str:
        ch = match.group(0)
        if ch in PUA_LIST_MARKERS:
            return PUA_LIST_MARKERS[ch]
        return replace_unknown

    cleaned = strip_nul_chars(text)
    return collapse_overdrawn_connector_labels(_PUA_RE.sub(_sub, cleaned))


def strip_nul_chars(value: Any) -> Any:
    """Remove U+0000 from strings (Postgres text/jsonb reject NUL). Recurse dict/list."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: strip_nul_chars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul_chars(v) for v in value]
    return value



def count_pua_markers(text: str) -> dict[str, int]:
    """Count known list-marker PUA codepoints in ``text``."""
    counts = {codepoint: 0 for codepoint in PUA_LIST_MARKERS}
    for ch in text:
        if ch in counts:
            counts[ch] += 1
    return {f"U+{ord(k):04X}": v for k, v in counts.items() if v}


def split_list_items(text: str) -> list[str]:
    """Split mapped list text into items on bullet boundaries."""
    mapped = map_pua(text)
    # After mapping, bullets are ordinary • characters.
    parts = re.split(r"(?=•)", mapped)
    items = [p.strip() for p in parts if p.strip() and p.strip() != "•"]
    return [re.sub(r"^•\s*", "", item).strip() for item in items]
