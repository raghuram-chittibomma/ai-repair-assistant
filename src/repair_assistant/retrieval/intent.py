"""Structured query intent for retrieval planning (agent control loop)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.query_expand import door_lock_polarity

# Door + lock topic without a clear unlock/lock polarity.
_DOOR_LOCK_TOPIC = re.compile(
    r"\bdoor\b.{0,40}\block|\block\b.{0,40}\bdoor\b",
    re.I,
)

_CLARIFY_DOOR = (
    "Is the door stuck closed (won't open / won't unlock), or will it not lock "
    "to start a cycle? If the display shows an error code (for example F5E2), "
    "please include it."
)


@dataclass(frozen=True)
class QueryIntent:
    """Compact understanding of the user message — labels only, no repair facts."""

    raw_query: str
    audience: str = "owner"
    # Codes the user actually wrote/said (assertable).
    user_codes: tuple[str, ...] = ()
    door_polarity: str | None = None  # unlock | lock | None
    ambiguous: bool = False
    clarify_question: str | None = None
    topic: str = "general"

    @property
    def error_codes(self) -> tuple[str, ...]:
        """Alias for ``user_codes`` (backward compatible)."""
        return self.user_codes

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguous and self.clarify_question)


def extract_intent(question: str, *, audience: str | None = None) -> QueryIntent:
    """Rule-based intent extraction (extensible; no LLM required for v1)."""
    q = (question or "").strip()
    aud = (audience or "owner").strip().lower() or "owner"
    user_codes = tuple(extract_error_codes(q))
    polarity = door_lock_polarity(q)
    topic = "general"
    ambiguous = False
    clarify: str | None = None

    if _DOOR_LOCK_TOPIC.search(q) or polarity is not None:
        topic = "door_lock"

    # Underspecified door/lock symptom: ask once instead of guessing polarity.
    if topic == "door_lock" and polarity is None and not user_codes:
        ambiguous = True
        clarify = _CLARIFY_DOOR

    return QueryIntent(
        raw_query=q,
        audience=aud,
        user_codes=user_codes,
        door_polarity=polarity,
        ambiguous=ambiguous,
        clarify_question=clarify,
        topic=topic,
    )


def intent_to_dict(intent: QueryIntent) -> dict:
    """JSON-serializable intent for Langfuse / debugging."""
    return {
        "raw_query": intent.raw_query,
        "audience": intent.audience,
        "user_codes": list(intent.user_codes),
        "error_codes": list(intent.user_codes),
        "door_polarity": intent.door_polarity,
        "ambiguous": intent.ambiguous,
        "clarify_question": intent.clarify_question,
        "topic": intent.topic,
        "needs_clarification": intent.needs_clarification,
    }


__all__ = [
    "QueryIntent",
    "extract_intent",
    "intent_to_dict",
]
