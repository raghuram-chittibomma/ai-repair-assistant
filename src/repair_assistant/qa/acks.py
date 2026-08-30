"""Detect acknowledgement-only follow-ups (checks passed / no findings)."""

from __future__ import annotations

import re

_ACK_ONLY_RE = re.compile(
    r"""^
    (?:
        (?:(?:ok|okay|yes|checked|done|yep)[\s.,]+)?
        (?:
        no\s+(?:issues?|problems?|errors?|faults?)
          (?:\s+(?:here|found|there|with\s+(?:that|those|these)|
              from\s+(?:these|those|the)\s+checks?))?
      | (?:that|this|it|they|those|these)\s+(?:also\s+)?(?:looks?|sounds|seems)\s+good
      | (?:all|everything)\s+(?:(?:looks|is|seems)\s+)?(?:good|fine|ok|clear|passed?)
      | (?:checks?|tests?)\s+(?:(?:all|look)\s+)?(?:pass(?:ed)?|ok|good|fine|clear)
      | (?:nothing|none)\s+(?:found|wrong|unusual)
      | looks?\s+good
      | (?:all\s+)?(?:clear|good|fine|ok)\.?
        )
    )
    [\s.!,]*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

ACK_IN_ASK_MODE = (
    "That sounds like a follow-up after checklist steps, but Ask mode is "
    "single-turn and has no prior symptom. Switch Mode to Diagnostic chat for "
    "multi-turn troubleshooting, or restate the symptom (for example "
    '"not washing properly").'
)

ORPHAN_ACK_IN_DIAGNOSE = (
    "It sounds like you're saying prior checks passed, but this diagnostic "
    "session does not have a symptom yet (session may have reset after an API "
    "restart). What is the appliance doing wrong — for example not washing "
    "properly, won't drain, or an error code on the display?"
)


def is_ack_only_message(text: str) -> bool:
    """True when the user only reports checks passed / no findings."""
    cleaned = " ".join((text or "").strip().split())
    if not cleaned or len(cleaned) > 120:
        return False
    return bool(_ACK_ONLY_RE.match(cleaned))


__all__ = [
    "ACK_IN_ASK_MODE",
    "ORPHAN_ACK_IN_DIAGNOSE",
    "is_ack_only_message",
]
