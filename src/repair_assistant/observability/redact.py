"""Optional serial redaction for Langfuse payloads (review R44).

Off by default. Free-text questions and symptoms are not rewritten — only
serial-shaped tokens and fields named ``serial`` / ``appliance_serial``.
"""

from __future__ import annotations

import os
import re
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files

# Two-letter prefix + 8+ digits (e.g. CF82012345). Skip W######## publication numbers.
_SERIAL_TOKEN = re.compile(r"\b(?![Ww]\d)[A-Za-z]{2}\d{8,}\b")
_SERIAL_KEYS = frozenset({"serial", "appliance_serial"})
_REDACTED = "[serial]"


def trace_redact_serial_enabled() -> bool:
    load_dotenv_files()
    return os.environ.get("REPAIR_TRACE_REDACT_SERIAL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def redact_for_trace(value: Any) -> Any:
    """Replace serial fields and serial-shaped tokens when the env flag is set."""
    if not trace_redact_serial_enabled():
        return value
    extras: list[str] = []
    _collect_serials(value, extras)
    return _walk(value, extras)


def _collect_serials(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _SERIAL_KEYS and item:
                token = str(item)
                if token not in found:
                    found.append(token)
            else:
                _collect_serials(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_serials(item, found)


def _redact_text(text: str, extras: list[str]) -> str:
    for extra in extras:
        if extra:
            text = text.replace(extra, _REDACTED)
    return _SERIAL_TOKEN.sub(_REDACTED, text)


def _walk(value: Any, extras: list[str]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, extras)
    if isinstance(value, dict):
        return {
            key: _REDACTED if key in _SERIAL_KEYS and item else _walk(item, extras)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_walk(item, extras) for item in value]
    return value
