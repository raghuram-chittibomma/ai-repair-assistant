"""LLM semantic knowledge units with human review (ADR-0047, ADR-0049).

The structured chunker (ADR-0007 / ADR-0022) stays the default path for every
document. This package is the opt-in second strategy: it segments a manufacturer
PDF into semantic knowledge units (native PDF or vision when scanned), keeps the
legacy representation serving traffic while a human reviews markers on the real
PDF, and cuts over atomically once the units are approved.
"""

from repair_assistant.semantic.lifecycle import (
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_READY,
    STATUS_SUPERSEDED,
    STRATEGY_SEMANTIC,
    STRATEGY_STRUCTURED,
    IngestionVersion,
    LifecycleError,
)

__all__ = [
    "STATUS_ABANDONED",
    "STATUS_ACTIVE",
    "STATUS_CANDIDATE",
    "STATUS_READY",
    "STATUS_SUPERSEDED",
    "STRATEGY_SEMANTIC",
    "STRATEGY_STRUCTURED",
    "IngestionVersion",
    "LifecycleError",
]
