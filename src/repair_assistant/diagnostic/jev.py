"""TypeSafe Jev Decision API client for diagnose closed-set labels (ADR-0054)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from repair_assistant.ingest.env import load_dotenv_files
from repair_assistant.qa.structured import DIAGNOSE_INTENT_LABELS

_log = logging.getLogger("repair_assistant.diagnostic.jev")

DEFAULT_JEV_MODEL = "jev-1.13.0"
#: Official TypeSafe Decision API (apikey_… keys). Alternate hosted mirror:
#: https://jevtypesafeai.com/api/v1/decide (expects jv_live_… keys).
DEFAULT_JEV_DECIDE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MIN_CONFIDENCE = 0.0
DEFAULT_JEV_TIMEOUT_SECONDS = 30.0

#: Criteria text mirrors prompts/diagnose_intent.txt (closed-set meanings).
LABEL_CRITERIA: dict[str, str] = {
    "ack": "prior checks passed / look good / no issues",
    "still_unresolved": "the last check was done and the symptom remains",
    "mid_cycle_stop": "wash stops mid-cycle or halfway, often with no error code",
    "new_symptom": "the user describes a different problem than the session symptom",
    "unclear": "cannot tell",
}

CLASSIFY_INSTRUCTIONS = (
    "Label one diagnose follow-up turn so search can stay on the session path. "
    "Pick exactly one label. Do not write a search query. Do not invent repair "
    "facts. Do not recommend parts or tests. Label only."
)


def jev_api_key() -> str:
    """Return JEV_API_KEY or empty when unset (soft — classify is optional)."""
    load_dotenv_files()
    return os.environ.get("JEV_API_KEY", "").strip()


def jev_model() -> str:
    load_dotenv_files()
    return os.environ.get("JEV_MODEL", DEFAULT_JEV_MODEL).strip() or DEFAULT_JEV_MODEL


def jev_decide_url() -> str:
    load_dotenv_files()
    return (
        os.environ.get("JEV_DECIDE_URL", DEFAULT_JEV_DECIDE_URL).strip()
        or DEFAULT_JEV_DECIDE_URL
    )


def jev_min_confidence() -> float:
    load_dotenv_files()
    raw = os.environ.get("JEV_MIN_CONFIDENCE", "").strip()
    if not raw:
        return DEFAULT_JEV_MIN_CONFIDENCE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_JEV_MIN_CONFIDENCE
    return value if value >= 0 else DEFAULT_JEV_MIN_CONFIDENCE


def jev_timeout_seconds() -> float:
    load_dotenv_files()
    raw = os.environ.get("JEV_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_JEV_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_JEV_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_JEV_TIMEOUT_SECONDS


def build_classify_state(*, board_text: str, transcript: str) -> str:
    """Same state payload shape as classify_diagnose_turn's user prompt."""
    lines = [
        board_text.strip() or "Session diagnostic board: (empty)",
        "",
        "Conversation so far:",
        transcript.strip() or "(start of session)",
    ]
    return "\n".join(lines)


def build_decide_body(*, state: str, model: str | None = None) -> dict[str, Any]:
    return {
        "model": model or jev_model(),
        "state": state,
        "questions": {
            "retrieve_label": {
                "type": "choice",
                "instructions": CLASSIFY_INSTRUCTIONS,
                "criteria": {
                    key: LABEL_CRITERIA[key] for key in DIAGNOSE_INTENT_LABELS
                },
            }
        },
    }


def parse_retrieve_label_answer(
    payload: dict[str, Any],
    *,
    min_confidence: float | None = None,
) -> str | None:
    """Extract a closed-set label from a /v1/decide response, or None."""
    floor = DEFAULT_JEV_MIN_CONFIDENCE if min_confidence is None else min_confidence
    answers = payload.get("answers") or {}
    answer = answers.get("retrieve_label") or {}
    if str(answer.get("type") or "") != "choice":
        return None
    choice = str(answer.get("choice") or "").strip()
    if choice not in DIAGNOSE_INTENT_LABELS:
        return None
    try:
        confidence = float(answer.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < floor:
        return None
    return choice


def decide(
    state: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST one decide call; raises on HTTP/transport errors."""
    key = (api_key if api_key is not None else jev_api_key()).strip()
    if not key:
        raise RuntimeError("JEV_API_KEY is required for Jev classify")
    endpoint = url or jev_decide_url()
    body = build_decide_body(state=state, model=model)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    wait = timeout if timeout is not None else jev_timeout_seconds()
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jev decide HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jev decide failed: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Jev decide returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Jev decide returned unexpected JSON")
    return payload


def classify_label(
    *,
    board_text: str,
    transcript: str,
    api_key: str | None = None,
    model: str | None = None,
    min_confidence: float | None = None,
) -> str | None:
    """Return a closed-set label, or None on miss / failure."""
    try:
        payload = decide(
            build_classify_state(board_text=board_text, transcript=transcript),
            api_key=api_key,
            model=model,
        )
        return parse_retrieve_label_answer(
            payload,
            min_confidence=(
                min_confidence
                if min_confidence is not None
                else jev_min_confidence()
            ),
        )
    except Exception:
        _log.warning("Jev diagnose classify failed; using retrieve fallback", exc_info=True)
        return None


def live_jev_intent_complete(system: str, user: str) -> str:
    """CompleteFn adapter: ignore system prompt; classify from user state text.

    Emits ``{"label": "..."}`` so :func:`parse_diagnose_label` stays shared.
    Raises on failure so :func:`classify_diagnose_turn` falls back.
    """
    del system  # Jev criteria carry label meanings; system prompt is unused.
    payload = decide(user)
    label = parse_retrieve_label_answer(
        payload, min_confidence=jev_min_confidence()
    )
    if label is None:
        raise RuntimeError("Jev classify returned no usable label")
    return json.dumps({"label": label})


__all__ = [
    "CLASSIFY_INSTRUCTIONS",
    "DEFAULT_JEV_MODEL",
    "LABEL_CRITERIA",
    "build_classify_state",
    "build_decide_body",
    "classify_label",
    "decide",
    "jev_api_key",
    "jev_decide_url",
    "jev_min_confidence",
    "jev_model",
    "jev_timeout_seconds",
    "live_jev_intent_complete",
    "parse_retrieve_label_answer",
]
