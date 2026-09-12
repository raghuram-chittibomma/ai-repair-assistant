"""Door lock/unlock polarity from English negation, not slang lists.

``doesn't open`` / ``won't open`` / ``can't get the door open`` share one
grammar after contractions fold. Idioms that are not negation + verb
(``got locked``) stay in ``query_expand.yaml``. See ADR-0040.
"""

from __future__ import annotations

import re

_APOS = str.maketrans({"\u2018": "'", "\u2019": "'", "`": "'", "´": "'"})

_CONTRACTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{left}\b"), right)
    for left, right in (
        ("won'?t", "will not"),
        ("wouldn'?t", "would not"),
        ("doesn'?t", "does not"),
        ("don'?t", "do not"),
        ("didn'?t", "did not"),
        ("can'?t", "cannot"),
        ("couldn'?t", "could not"),
        ("isn'?t", "is not"),
        ("wasn'?t", "was not"),
        ("hasn'?t", "has not"),
        ("haven'?t", "have not"),
        ("ain'?t", "is not"),
    )
)

# Inputs that already lost the apostrophe (``doesnt open``).
_STRIPPED_CONTRACTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{left}\b"), right)
    for left, right in (
        ("wont", "will not"),
        ("wouldnt", "would not"),
        ("doesnt", "does not"),
        ("dont", "do not"),
        ("didnt", "did not"),
        ("cant", "cannot"),
        ("couldnt", "could not"),
        ("isnt", "is not"),
        ("wasnt", "was not"),
        ("hasnt", "has not"),
        ("havent", "have not"),
        ("aint", "is not"),
    )
)

_AUX_NEG = r"(?:will|would|does|do|did|can|could|is|was|has|have)\s+not|cannot"
_OPEN = r"open|opening|unlock|unlocking"

_UNLOCK_NEG = re.compile(rf"\b(?:{_AUX_NEG}).{{0,28}}\b(?:{_OPEN})\b")
_UNLOCK_FAIL = re.compile(rf"\b(?:failed|unable)\s+to\s+(?:{_OPEN})\b")
# Infinitive after will/does/can — not the adjective ``is not locked``.
_LOCK_NEG = re.compile(
    r"\b(?:will|would|does|do|did|can|could)\s+not\s+(?:lock|latch)\b"
    r"|\bcannot\s+(?:lock|latch)\b"
)
_LOCK_GERUND = re.compile(r"\bnot\s+locking\b")
_LOCK_FAIL = re.compile(r"\b(?:failed|unable)\s+to\s+(?:lock|latch)\b")


def fold_user_query(text: str) -> str:
    """Lowercase, expand contractions, collapse space."""
    q = (text or "").translate(_APOS).lower()
    for pat, repl in _CONTRACTIONS:
        q = pat.sub(repl, q)
    q = q.replace("'", "")
    for pat, repl in _STRIPPED_CONTRACTIONS:
        q = pat.sub(repl, q)
    return " ".join(q.split())


def compositional_door_polarity(query: str) -> str | None:
    """``unlock`` / ``lock`` from negation × lemma, or None if both/neither."""
    q = fold_user_query(query)
    if not q:
        return None
    unlock = bool(_UNLOCK_NEG.search(q) or _UNLOCK_FAIL.search(q))
    lock = bool(_LOCK_NEG.search(q) or _LOCK_GERUND.search(q) or _LOCK_FAIL.search(q))
    if unlock and not lock:
        return "unlock"
    if lock and not unlock:
        return "lock"
    return None


__all__ = [
    "compositional_door_polarity",
    "fold_user_query",
]
