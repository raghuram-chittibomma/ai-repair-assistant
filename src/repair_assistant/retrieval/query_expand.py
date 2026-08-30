"""Load curator-owned query expansion from YAML (OEM phrases only)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_APOS = str.maketrans({"\u2018": "'", "\u2019": "'", "`": "'"})


@dataclass(frozen=True)
class ExpandFamily:
    family_id: str
    polarity: str | None
    mid_cycle: bool
    triggers: tuple[str, ...]
    pairs: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    expand: str


def query_expand_config_path() -> Path:
    env = os.environ.get("REPAIR_QUERY_EXPAND_CONFIG", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "retrieval" / "query_expand.yaml"
        if candidate.is_file():
            return candidate
    return here.parents[3] / "config" / "retrieval" / "query_expand.yaml"


def _normalize(text: str) -> str:
    cleaned = (text or "").translate(_APOS).replace("'", "")
    return " ".join(cleaned.lower().split())


def _phrase_in(query: str, phrase: str) -> bool:
    q = _normalize(query)
    p = _normalize(phrase)
    if not q or not p:
        return False
    return bool(re.search(rf"\b{re.escape(p)}\b", q))


def _pair_in(query: str, left: str, right: str) -> bool:
    q = _normalize(query)
    a = _normalize(left)
    b = _normalize(right)
    if not q or not a or not b:
        return False
    return bool(re.search(rf"\b{re.escape(a)}\s+{re.escape(b)}\b", q))


def _family_matches(family: ExpandFamily, query: str) -> bool:
    if any(_phrase_in(query, phrase) for phrase in family.triggers):
        return True
    for lefts, rights in family.pairs:
        if any(_pair_in(query, left, right) for left in lefts for right in rights):
            return True
    return False


def _parse_family(raw: object) -> ExpandFamily:
    if not isinstance(raw, dict):
        raise ValueError("Each family in query_expand.yaml must be a mapping")
    family_id = str(raw.get("id") or "").strip()
    if not family_id:
        raise ValueError("Each family needs an id")
    polarity = str(raw.get("polarity") or "").strip().lower() or None
    if polarity not in (None, "unlock", "lock"):
        raise ValueError(f"{family_id}: polarity must be unlock, lock, or omitted")
    triggers = tuple(
        str(item).strip()
        for item in (raw.get("when_user_says") or [])
        if str(item).strip()
    )
    pairs: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for row in raw.get("phrase_pairs") or []:
        if not isinstance(row, dict):
            raise ValueError(f"{family_id}: phrase_pairs entries must be mappings")
        lefts = tuple(str(x).strip() for x in (row.get("from") or []) if str(x).strip())
        rights = tuple(str(x).strip() for x in (row.get("then") or []) if str(x).strip())
        if lefts and rights:
            pairs.append((lefts, rights))
    expand = " ".join(
        str(item).strip()
        for item in (raw.get("add_to_search") or [])
        if str(item).strip()
    )
    if not triggers and not pairs:
        raise ValueError(f"{family_id}: add when_user_says or phrase_pairs")
    if not expand:
        raise ValueError(f"{family_id}: add_to_search cannot be empty")
    return ExpandFamily(
        family_id=family_id,
        polarity=polarity,
        mid_cycle=bool(raw.get("mid_cycle")),
        triggers=triggers,
        pairs=tuple(pairs),
        expand=expand,
    )


@lru_cache(maxsize=4)
def _load_families(path_str: str) -> tuple[ExpandFamily, ...]:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(
            f"Query expansion list not found: {path}. "
            "Expected config/retrieval/query_expand.yaml"
        )
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = payload.get("families")
    if not isinstance(rows, list) or not rows:
        raise ValueError("query_expand.yaml must have a non-empty families list")
    return tuple(_parse_family(row) for row in rows)


def load_expand_families(path: Path | None = None) -> tuple[ExpandFamily, ...]:
    """Return expansion families from YAML (cached per path)."""
    return _load_families(str(path or query_expand_config_path()))


def door_lock_polarity(query: str) -> str | None:
    """Return ``unlock``, ``lock``, or None when polarity is clear."""
    unlock = False
    lock = False
    for family in load_expand_families():
        if family.polarity == "unlock" and _family_matches(family, query):
            unlock = True
        elif family.polarity == "lock" and _family_matches(family, query):
            lock = True
    if unlock and not lock:
        return "unlock"
    if lock and not unlock:
        return "lock"
    return None


def expansion_phrases_for_polarity(polarity: str | None) -> str:
    """OEM synonym phrases for a known door-lock polarity (empty if unknown)."""
    if polarity not in ("unlock", "lock"):
        return ""
    for family in load_expand_families():
        if family.polarity == polarity:
            return family.expand
    return ""


def expansion_phrases_for_query(query: str) -> str:
    """Extra OEM phrases from query shape (door polarity + mid-cycle stop)."""
    parts: list[str] = []
    polarity = door_lock_polarity(query)
    door = expansion_phrases_for_polarity(polarity)
    if door:
        parts.append(door)
    if is_mid_cycle_stop_query(query):
        for family in load_expand_families():
            if family.mid_cycle:
                parts.append(family.expand)
    return " ".join(parts).strip()


def is_mid_cycle_stop_query(query: str) -> bool:
    """True when the question looks like a mid-cycle / no-code stop symptom."""
    return any(
        family.mid_cycle and _family_matches(family, query)
        for family in load_expand_families()
    )


def expand_retrieval_query(query: str) -> str:
    """Augment the embedding query with OEM synonym phrases.

    Prefer ``plan_retrieval(extract_intent(...))`` in new call sites; this helper
    remains for tests and direct use.
    """
    q = (query or "").strip()
    if not q:
        return q
    phrases = expansion_phrases_for_query(q)
    return f"{q} {phrases}".strip() if phrases else q


__all__ = [
    "ExpandFamily",
    "door_lock_polarity",
    "expand_retrieval_query",
    "expansion_phrases_for_polarity",
    "expansion_phrases_for_query",
    "is_mid_cycle_stop_query",
    "load_expand_families",
    "query_expand_config_path",
]
