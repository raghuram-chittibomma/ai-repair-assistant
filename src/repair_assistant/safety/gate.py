"""Apply safety policy to LLM output deterministically."""

from __future__ import annotations

from repair_assistant.safety.models import (
    Audience,
    SafetyAction,
    SafetyAssessment,
    SafetyGateResult,
)
from repair_assistant.safety.policy import (
    _UNGROUNDED_ABSTAIN,
    _VOLTAGE_WARNING,
    block_message,
    escalate_message,
    needs_grounding_citation,
    output_hazard,
)

_OWNER_NOTICE = (
    "Safety notice: Unplug the appliance or disconnect power before any "
    "inspection or service unless the manufacturer evidence explicitly "
    "states otherwise."
)

_OWNER_TECH_ESCALATE_REASON = (
    "Service technician procedures (diagnostic TESTs or live voltage) are not "
    "provided step-by-step for owners."
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
    hazard = output_hazard(assessment, text)
    if hazard == "output-bypass":
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

    # G1: owners must not receive TEST # / live-voltage walkthroughs.
    if hazard == "owner-tech-procedure":
        esc = SafetyAssessment(
            action=SafetyAction.ESCALATE,
            rule_id="owner-tech-procedure",
            reason=_OWNER_TECH_ESCALATE_REASON,
            audience=Audience.OWNER,
        )
        return SafetyGateResult(
            text=escalate_message(esc),
            action=SafetyAction.ESCALATE,
            rule_id="owner-tech-procedure",
            notice=_OWNER_TECH_ESCALATE_REASON,
            escalated=True,
            blocked=False,
        )

    if hazard is not None:
        # Owner + escalate + unsafe procedure; `hazard` is the assessment rule id.
        return SafetyGateResult(
            text=escalate_message(assessment),
            action=SafetyAction.ESCALATE,
            rule_id=assessment.rule_id,
            notice=assessment.reason,
            escalated=True,
        )

    # G3: procedural checklist / service steps without [n] citations.
    if needs_grounding_citation(text):
        return SafetyGateResult(
            text=_UNGROUNDED_ABSTAIN,
            action=SafetyAction.ALLOW,
            rule_id="ungrounded-procedure",
            notice="Procedural answer lacked evidence citations.",
            blocked=True,
            escalated=False,
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
