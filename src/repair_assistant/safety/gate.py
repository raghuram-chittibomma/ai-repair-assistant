"""Apply safety policy to LLM output deterministically."""

from __future__ import annotations

from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment, SafetyGateResult
from repair_assistant.safety.policy import (
    _FORBIDDEN_OUTPUT,
    _UNSAFE_PROCEDURE,
    _VOLTAGE_WARNING,
    block_message,
    escalate_message,
)

_OWNER_NOTICE = (
    "Safety notice: Unplug the appliance or disconnect power before any "
    "inspection or service unless the manufacturer evidence explicitly "
    "states otherwise."
)


def gate_answer(
    assessment: SafetyAssessment,
    answer: str,
    *,
    evidence_text: str = "",
) -> SafetyGateResult:
    """Post-LLM gate — enforce policy even if the model oversteps."""
    if assessment.action == SafetyAction.BLOCK:
        return SafetyGateResult(
            text=block_message(assessment),
            action=SafetyAction.BLOCK,
            rule_id=assessment.rule_id,
            notice=assessment.reason,
            blocked=True,
            escalated=True,
        )

    text = answer.strip()
    if _FORBIDDEN_OUTPUT.search(text):
        return SafetyGateResult(
            text=block_message(
                SafetyAssessment(
                    action=SafetyAction.BLOCK,
                    rule_id="output-bypass",
                    reason="Output contained interlock bypass language.",
                    audience=assessment.audience,
                )
            ),
            action=SafetyAction.BLOCK,
            rule_id="output-bypass",
            notice="Interlock bypass instructions were removed.",
            blocked=True,
            escalated=True,
        )

    if assessment.audience == Audience.OWNER and assessment.action == SafetyAction.ESCALATE:
        if _UNSAFE_PROCEDURE.search(text):
            return SafetyGateResult(
                text=escalate_message(assessment),
                action=SafetyAction.ESCALATE,
                rule_id=assessment.rule_id,
                notice=assessment.reason,
                escalated=True,
            )

    notice = ""
    if assessment.action == SafetyAction.WARN:
        notice = assessment.reason
        if _VOLTAGE_WARNING.search(evidence_text) and not _VOLTAGE_WARNING.search(text):
            text = f"{_OWNER_NOTICE}\n\n{text}"

    if assessment.audience == Audience.OWNER and assessment.action == SafetyAction.ESCALATE:
        notice = assessment.reason
        if not text.upper().startswith("ESCALATE:"):
            # Keep diagnostic explanation but prepend escalation framing.
            if "qualified" not in text.lower() and "service" not in text.lower():
                text = f"{escalate_message(assessment)}\n\n{text}"

    return SafetyGateResult(
        text=text,
        action=assessment.action,
        rule_id=assessment.rule_id,
        notice=notice,
        escalated=assessment.action in {SafetyAction.ESCALATE, SafetyAction.BLOCK},
        blocked=False,
    )
