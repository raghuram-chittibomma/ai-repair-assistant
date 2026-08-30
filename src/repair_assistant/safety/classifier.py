"""Optional LLM safety arm (ADR-0032 / review R3). Regex remains the CI gate."""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

from repair_assistant.prompts import safety_classifier as safety_classifier_prompt
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment
from repair_assistant.safety.policy import assess_request, directive_for, severity

_log = logging.getLogger("repair_assistant.safety")

SAFETY_CLASSIFIER_SCHEMA: dict = {
    "name": "safety_assessment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["allow", "warn", "escalate", "block"],
            },
            "rule_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["action", "rule_id", "reason"],
    },
}

SAFETY_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": SAFETY_CLASSIFIER_SCHEMA,
}

_ACTIONS = {item.value: item for item in SafetyAction if item != SafetyAction.UNGROUNDED}


class SafetyClassifier(Protocol):
    def classify(self, question: str, audience: Audience) -> SafetyAssessment | None:
        """Return a proposed assessment, or None to keep the regex result."""


def merge_assessments(
    regex: SafetyAssessment, extra: SafetyAssessment | None
) -> SafetyAssessment:
    """Union: extra may raise severity, never lower it."""
    if extra is None:
        return regex
    if severity(extra.action) <= severity(regex.action):
        return regex
    rule_id = extra.rule_id.strip() or "llm-other"
    if not rule_id.startswith("llm-"):
        rule_id = f"llm-{rule_id}"
    return SafetyAssessment(
        action=extra.action,
        rule_id=rule_id[:64],
        reason=(extra.reason or regex.reason).strip(),
        audience=regex.audience,
        prompt_directive=directive_for(extra.action, regex.audience),
    )


def parse_classifier_output(raw: str, *, audience: Audience) -> SafetyAssessment | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    action = _ACTIONS.get(str(data.get("action") or "").strip().lower())
    if action is None:
        return None
    return SafetyAssessment(
        action=action,
        rule_id=str(data.get("rule_id") or "other"),
        reason=str(data.get("reason") or "").strip(),
        audience=audience,
    )


def assess_layered(
    question: str,
    *,
    audience: Audience = Audience.OWNER,
    classifier: SafetyClassifier | None = None,
) -> SafetyAssessment:
    """Regex first; optional classifier may only raise severity (ADR-0032)."""
    regex = assess_request(question, audience=audience)
    if classifier is None or regex.action == SafetyAction.BLOCK:
        return regex
    try:
        extra = classifier.classify(question, audience)
    except Exception:  # noqa: BLE001 — classifier must not fail the product path
        _log.warning("Safety classifier failed; keeping regex assessment", exc_info=True)
        return regex
    return merge_assessments(regex, extra)


class OpenAISafetyClassifier:
    """Small structured completion. Failures surface as None via assess_layered."""

    def __init__(self, llm=None) -> None:
        self._llm = llm

    def classify(self, question: str, audience: Audience) -> SafetyAssessment | None:
        client = self._llm or _openai_client()
        user = f"Audience: {audience.value}\nMessage: {question.strip()}"
        raw = client.complete(safety_classifier_prompt(), user)
        return parse_classifier_output(raw, audience=audience)


def runtime_classifier() -> OpenAISafetyClassifier | None:
    """None unless an OpenAI key is set. Never raises."""
    from repair_assistant.qa.env import load_dotenv_files

    load_dotenv_files()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    return OpenAISafetyClassifier()


def _openai_client():
    from repair_assistant.qa.env import llm_model, openai_api_key
    from repair_assistant.qa.generate import OpenAIClient

    return OpenAIClient(
        api_key=openai_api_key(),
        model=llm_model(),
        prompt_name="safety_classifier",
        response_format=SAFETY_RESPONSE_FORMAT,
        max_tokens=80,
    )
