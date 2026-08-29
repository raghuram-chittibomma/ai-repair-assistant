"""Incremental safety gate for streamed generation (review finding R1).

The post-LLM gate in `safety.gate` is the authority on what a caller may see, but
it can only run on a finished answer. A token-by-token stream that yields deltas
straight from the provider therefore delivers ungated text and repairs it
afterwards — the unsafe content is already on the wire, in the DOM, and in any
capture. That defeats ADR-0014's central claim that policy holds "even if the
model oversteps".

This module closes that gap without giving up streaming, in two parts:

**Refuse to stream at all** when the pre-generation assessment already says the
answer cannot be shown as written (`may_stream`). A blocked question, or an owner
asking something that must escalate, has a known outcome before the first token.

**Release incrementally, behind the hazard guards** otherwise (`StreamGate`).
Deltas accumulate; text is only released once the guards have been run over
everything accumulated so far.

The invariant this provides:

    No complete hazard-pattern match is ever released.

It holds because the guards are run over the whole accumulation before any of it
is released, and release stops permanently once a guard trips. A match wholly
inside already-released text would have tripped an earlier check; a match that
completes later stops the stream before its final characters go out. What can
still be released is a *prefix* of a hazard phrase whose remainder never arrives —
"disconnect the" without what follows — which is not the hazard, and is further
limited by holding back `MAX_HAZARD_MATCH_CHARS` of tail.

The grounding check (G3) is deliberately not enforced here. It is not monotone in
the answer text: a procedure with no citation yet may cite before it ends. It stays
a whole-answer decision in `gate_answer`, whose result is authoritative and which
the client applies on the terminal event.
"""

from __future__ import annotations

from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment
from repair_assistant.safety.policy import MAX_HAZARD_MATCH_CHARS, output_hazard

#: Boundaries to break released text on, widest first, so a release never splits
#: a word and rarely splits a sentence.
_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


def may_stream(assessment: SafetyAssessment) -> bool:
    """False when the outcome is already decided and no token should be shown.

    `gate_answer` replaces the answer wholesale in both of these cases, so
    streaming the model's draft would only show text that is guaranteed to be
    withdrawn.
    """
    if assessment.action == SafetyAction.BLOCK:
        return False
    return not (
        assessment.audience == Audience.OWNER
        and assessment.action == SafetyAction.ESCALATE
    )


class StreamGate:
    """Hold back streamed text until the hazard guards have cleared it."""

    def __init__(
        self,
        assessment: SafetyAssessment,
        *,
        holdback: int = MAX_HAZARD_MATCH_CHARS,
    ) -> None:
        self._assessment = assessment
        self._holdback = max(0, holdback)
        self._buffer: list[str] = []
        self._accumulated = ""
        self._released = 0
        self._hazard: str | None = None

    @property
    def accumulated(self) -> str:
        """Everything received from the model, released or not."""
        return self._accumulated

    @property
    def hazard(self) -> str | None:
        """Rule id that stopped the stream, or None."""
        return self._hazard

    @property
    def tripped(self) -> bool:
        return self._hazard is not None

    @property
    def released(self) -> str:
        return self._accumulated[: self._released]

    def push(self, delta: str) -> str:
        """Accept a delta; return the text that is now safe to release.

        Returns `""` when nothing can be released yet, and after the gate has
        tripped. Callers keep feeding deltas after a trip so that the complete
        draft is still available for the authoritative final gate and for tracing.
        """
        self._buffer.append(delta)
        self._accumulated = "".join(self._buffer)
        if self._hazard is not None:
            return ""

        hazard = output_hazard(self._assessment, self._accumulated)
        if hazard is not None:
            self._hazard = hazard
            return ""

        return self._advance(len(self._accumulated) - self._holdback)

    def finish(self) -> str:
        """Release whatever tail remains, if the guards never tripped."""
        if self._hazard is not None:
            return ""
        # Re-check: the tail has not been guarded at full length yet.
        hazard = output_hazard(self._assessment, self._accumulated)
        if hazard is not None:
            self._hazard = hazard
            return ""
        return self._advance(len(self._accumulated), exact=True)

    def _advance(self, limit: int, *, exact: bool = False) -> str:
        if limit <= self._released:
            return ""
        cut = limit if exact else self._boundary(limit)
        if cut <= self._released:
            return ""
        chunk = self._accumulated[self._released : cut]
        self._released = cut
        return chunk

    def _boundary(self, limit: int) -> int:
        """Largest index at or below `limit` that ends on a natural boundary."""
        window = self._accumulated[self._released : limit]
        for token in _BOUNDARIES:
            idx = window.rfind(token)
            if idx != -1:
                return self._released + idx + len(token)
        return self._released
