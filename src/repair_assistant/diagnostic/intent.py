"""Closed-set diagnose retrieve labels (ADR-0039)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.prompts import diagnose_intent
from repair_assistant.qa.structured import DIAGNOSE_INTENT_LABELS, _try_json
from repair_assistant.retrieval.search import Hit

_log = logging.getLogger("repair_assistant.diagnostic")

LABELS = frozenset(DIAGNOSE_INTENT_LABELS)
ANCHOR_LABELS = frozenset({"ack", "still_unresolved", "unclear"})
_DEMOTE_MIN_CHARS = 12
_TEST_NUM = re.compile(r"\btest\s*#\s*(\d+)\b", re.I)

CompleteFn = Callable[[str, str], str]


def parse_diagnose_label(raw: str) -> str | None:
    loaded = _try_json(raw or "")
    if loaded is None:
        text = (raw or "").strip()
        if text in LABELS:
            return text
        return None
    label = str(loaded.get("label") or "").strip()
    return label if label in LABELS else None


def build_classify_user_prompt(*, board_text: str, transcript: str) -> str:
    lines = [
        board_text.strip() or "Session diagnostic board: (empty)",
        "",
        "Conversation so far:",
        transcript.strip() or "(start of session)",
    ]
    return "\n".join(lines)


def classify_diagnose_turn(
    *,
    board_text: str,
    transcript: str,
    complete: CompleteFn | None = None,
) -> str | None:
    """Return a closed-set label, or None to use the regex retrieve fallback."""
    if complete is None:
        return None
    try:
        raw = complete(diagnose_intent(), build_classify_user_prompt(
            board_text=board_text, transcript=transcript
        ))
    except Exception:
        _log.warning("diagnose intent classify failed; using retrieve fallback")
        return None
    return parse_diagnose_label(raw)


def live_intent_complete(system: str, user: str) -> str:
    from repair_assistant.qa.env import llm_model, openai_api_key
    from repair_assistant.qa.generate import OpenAIClient

    key = openai_api_key()
    if not key:
        raise RuntimeError("no openai key")
    client = OpenAIClient(
        api_key=key,
        model=llm_model(),
        prompt_name="diagnose_intent",
        max_tokens=40,
    )
    return client.complete(system, user)


def session_codes(texts: Sequence[str]) -> list[str]:
    codes: list[str] = []
    for text in texts:
        codes.extend(extract_error_codes(text))
    return sorted(set(codes))


def query_for_label(
    label: str,
    *,
    anchor: str,
    latest: str,
    codes: Sequence[str],
) -> str:
    """Rule-built search string. The model never supplies query text."""
    if label == "mid_cycle_stop" or label == "new_symptom":
        query = (latest or anchor or "").strip()
    else:
        query = (anchor or latest or "").strip()
    unique = [c for c in codes if c]
    if unique:
        query = f"{' '.join(unique)} {query}".strip()
    return query


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def procedure_needles(text: str) -> list[str]:
    """TEST #N mentions — short but enough to drop a completed procedure."""
    return [f"test #{num}" for num in _TEST_NUM.findall(text or "")]


def _overlaps_demote(hit_text: str, needles: Sequence[str]) -> bool:
    hay = _norm(hit_text)
    if not hay:
        return False
    hay_tests = {n.lower() for n in _TEST_NUM.findall(hay)}
    for raw in needles:
        needle = _norm(raw)
        for num in _TEST_NUM.findall(needle):
            if num.lower() in hay_tests:
                return True
        if len(needle) < _DEMOTE_MIN_CHARS:
            continue
        if needle in hay or hay in needle:
            return True
    return False


def stick_diagnose_hits(
    hits: Sequence[Hit],
    *,
    prefer_doc_ids: Sequence[str] | None = None,
    demote_texts: Sequence[str] | None = None,
) -> list[Hit]:
    """Prefer last cited doc for new checks; demote the completed check anywhere."""
    prefer = {str(d) for d in (prefer_doc_ids or []) if str(d).strip()}
    needles = [t for t in (demote_texts or []) if _norm(t)]

    def rank(hit: Hit) -> tuple[int, float]:
        preferred = bool(prefer) and hit.doc_id in prefer
        demoted = _overlaps_demote(hit.text, needles)
        # 0 = preferred and still open, 1 = other open, 2 = completed check
        if demoted:
            bucket = 2
        elif preferred:
            bucket = 0
        else:
            bucket = 1
        return (bucket, -float(hit.score))

    return sorted(hits, key=rank)


def demote_texts_from_board(
    board: dict[str, Any] | None,
    *,
    extra: Sequence[str] | None = None,
) -> list[str]:
    if not isinstance(board, dict):
        board = {}
    out: list[str] = []
    for item in board.get("ruled_out") or []:
        text = str(item or "").strip()
        if text:
            out.append(text)
            out.extend(procedure_needles(text))
    next_check = str(board.get("next_check") or "").strip()
    if next_check:
        out.append(next_check)
        out.extend(procedure_needles(next_check))
    for blob in extra or []:
        out.extend(procedure_needles(str(blob or "")))
    return out


def last_doc_ids_from_citations(citations: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for cite in citations:
        doc = getattr(cite, "doc_id", None)
        if doc is None and isinstance(cite, dict):
            doc = cite.get("doc_id")
        text = str(doc or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


__all__ = [
    "ANCHOR_LABELS",
    "LABELS",
    "build_classify_user_prompt",
    "classify_diagnose_turn",
    "live_intent_complete",
    "demote_texts_from_board",
    "procedure_needles",
    "last_doc_ids_from_citations",
    "parse_diagnose_label",
    "query_for_label",
    "session_codes",
    "stick_diagnose_hits",
]
