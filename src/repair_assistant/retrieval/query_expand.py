"""Grounded retrieval query expansion (OEM synonym phrases only)."""

from __future__ import annotations

import re

# Stuck closed / will not open — often mis-retrieved as "Door won't lock".
_STUCK_LOCKED = re.compile(
    r"\b("
    r"got locked|stuck locked|locked shut|door (?:is |was )?locked|"
    r"won'?t open|will not open|can'?t open|cannot open|"
    r"won'?t unlock|will not unlock|can'?t unlock|cannot unlock|"
    r"door will not unlock|will not unlock"
    r")\b",
    re.I,
)

# Will not latch / start — opposite polarity.
_WONT_LOCK = re.compile(
    r"\b("
    r"won'?t lock|will not lock|doesn'?t lock|does not lock|"
    r"not locking|failed to lock|door not lock|"
    r"door won'?t lock|door will not lock"
    r")\b",
    re.I,
)

# Phrases that appear in Whirlpool owner/service literature (not invented).
_UNLOCK_EXPANSION = (
    "door will not unlock door will not open lock failure F5E2 "
    "Door locks when cycle has started"
)
_LOCK_EXPANSION = "Door Won't Lock door not closed Ensure that door is completely closed"


def door_lock_polarity(query: str) -> str | None:
    """Return ``unlock``, ``lock``, or None when polarity is clear."""
    stuck = bool(_STUCK_LOCKED.search(query or ""))
    wont = bool(_WONT_LOCK.search(query or ""))
    if stuck and not wont:
        return "unlock"
    if wont and not stuck:
        return "lock"
    return None


def expansion_phrases_for_polarity(polarity: str | None) -> str:
    """OEM synonym phrases for a known door-lock polarity (empty if unknown)."""
    if polarity == "unlock":
        return _UNLOCK_EXPANSION
    if polarity == "lock":
        return _LOCK_EXPANSION
    return ""


def expand_retrieval_query(query: str) -> str:
    """Augment the embedding query with OEM synonym phrases for lock polarity.

    Prefer ``plan_retrieval(extract_intent(...))`` in new call sites; this helper
    remains for tests and direct use.
    """
    q = (query or "").strip()
    if not q:
        return q
    phrases = expansion_phrases_for_polarity(door_lock_polarity(q))
    return f"{q} {phrases}".strip() if phrases else q


__all__ = [
    "door_lock_polarity",
    "expand_retrieval_query",
    "expansion_phrases_for_polarity",
]
