"""Lightweight language hints for multi-language Whirlpool PDFs."""

from __future__ import annotations

_FR_MARKERS = (
    "débran",
    "laveuse",
    "avertissement",
    "bulletin technique",
    "rév",
    "pour communication",
)
_ES_MARKERS = (
    "desenchufe",
    "lavadora",
    "advertencia",
    "boletín",
    "técnico",
    "para la atención",
)


def detect_language(text: str) -> str | None:
    """Return ``en``, ``fr``, ``es``, or None if undecided.

    Marker counts are deliberately small and ASCII-foldable enough to run on
    extracted PDF text without an NLP dependency.
    """
    lowered = text.lower()
    fr = sum(1 for m in _FR_MARKERS if m in lowered)
    es = sum(1 for m in _ES_MARKERS if m in lowered)
    if fr >= 2 and fr > es:
        return "fr"
    if es >= 2 and es > fr:
        return "es"
    if fr == 0 and es == 0 and len(text.strip()) > 40:
        return "en"
    if fr == 0 and es == 0:
        return None
    return "en" if fr == es else ("fr" if fr > es else "es")
