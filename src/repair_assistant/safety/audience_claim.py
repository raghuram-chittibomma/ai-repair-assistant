"""Self-asserted audience claims (review R2).

The safety model is audience-tiered. The tier is chosen by the caller; this
module records that claim. It does not verify technician credentials — that
is a permanent non-goal (ADR-0025).
"""

from __future__ import annotations

import logging
from typing import Any

from repair_assistant.safety.models import Audience

_log = logging.getLogger("repair_assistant.safety")

TECHNICIAN_ATTESTATION_NOTICE = (
    "Technician status is self-asserted and is not verified. "
    "Live-voltage TEST procedures may be shown."
)


def record_audience_claim(
    audience: Audience | str,
    *,
    attested: bool = False,
    source: str = "request",
) -> dict[str, Any]:
    """Log a technician claim and return trace metadata. Never verifies."""
    value = audience.value if isinstance(audience, Audience) else str(audience)
    technician = value == Audience.TECHNICIAN.value
    meta = {
        "audience": value,
        "audience_verified": False,
        "technician_attested": bool(attested) if technician else False,
    }
    if technician:
        _log.info(
            "audience_claim audience=technician verified=false attested=%s source=%s",
            meta["technician_attested"],
            source,
        )
    return meta
