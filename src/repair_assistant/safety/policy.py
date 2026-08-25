"""Deterministic repair-risk rules — the LLM is not the sole safety authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment

# Ordered highest-severity first within each audience.
_BLOCK = [
    (
        "bypass-interlock",
        re.compile(
            r"\b(bypass|jumper|jump|defeat|disable)\b.{0,40}\b(door|lock|interlock|lid)\b"
            r"|\b(door|lock|interlock|lid)\b.{0,40}\b(bypass|jumper|jump|defeat|disable)\b",
            re.I,
        ),
        "Requests to bypass or defeat door or lid interlocks are not provided.",
    ),
]

_ESCALATE_OWNER = [
    (
        "live-voltage",
        re.compile(
            r"\b(measure|check|test)\b.{0,30}\b(voltage|120\s*v|240\s*v|vac|live)\b"
            r"|\b(voltage|120\s*v|240\s*v|vac)\b.{0,30}\b(measure|measurement|check|test)\b"
            r"|\blive\s+voltage\b|\bwith\s+power\s+on\b|\benergized\b",
            re.I,
        ),
        "Live voltage measurements require qualified appliance service personnel.",
    ),
    (
        "control-board-service",
        re.compile(
            r"\b(replace|remove|install|swap)\b.{0,30}\b(acu|control\s+board|main\s+control|ccu)\b"
            r"|\bdisassemble\b",
            re.I,
        ),
        "Control board replacement and disassembly require qualified service.",
    ),
    (
        "panel-access",
        re.compile(
            r"\b(remove|take\s+off)\b.{0,20}\b(rear|front|top|bottom|service)\s+panel\b",
            re.I,
        ),
        "Panel removal exposes live components and requires qualified service.",
    ),
]

_WARN_OWNER = [
    (
        "reset-and-power",
        re.compile(
            r"\b(unplug|disconnect\s+power|cycle\s+power|hard\s+reset)\b",
            re.I,
        ),
        "Follow manufacturer power-disconnect guidance before servicing.",
    ),
]

# Technician may receive procedural detail but warnings still apply.
_ESCALATE_TECH = [
    (
        "bypass-interlock",
        _BLOCK[0][1],
        _BLOCK[0][2],
    ),
]

_WARN_TECH = [
    (
        "live-voltage",
        _ESCALATE_OWNER[0][1],
        "Preserve all voltage and shock-hazard warnings from the evidence.",
    ),
    (
        "panel-access",
        _ESCALATE_OWNER[2][1],
        "Panel removal exposes live components — preserve disconnect warnings.",
    ),
]

_ESCALATION_TEMPLATE = (
    "ESCALATE: {reason} I can explain what the manufacturer documentation "
    "describes, but I cannot provide step-by-step instructions for this "
    "procedure for your audience level. Contact qualified appliance service."
)

_BLOCK_TEMPLATE = (
    "BLOCK: {reason} Contact qualified appliance service for this issue."
)

_PROMPT_ESCALATE = (
    "Safety policy: do NOT provide step-by-step live-voltage, disassembly, "
    "panel-removal, or control-board replacement instructions to this user. "
    "Explain the diagnosis or error meaning from the evidence and recommend "
    "qualified appliance service for hands-on repair."
)

_PROMPT_WARN = (
    "Safety policy: if the evidence includes shock, voltage, or disassembly "
    "warnings, reproduce them verbatim. Do not omit disconnect-power guidance."
)

_PROMPT_TECH = (
    "Audience: qualified appliance service personnel. Procedural steps from "
    "the evidence may be cited, but never omit manufacturer warnings."
)


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern[str]
    reason: str
    action: SafetyAction


def _rules_for(audience: Audience) -> list[_Rule]:
    rules: list[_Rule] = []
    for rule_id, pattern, reason in _BLOCK:
        rules.append(_Rule(rule_id, pattern, reason, SafetyAction.BLOCK))

    if audience == Audience.OWNER:
        for rule_id, pattern, reason in _ESCALATE_OWNER:
            rules.append(_Rule(rule_id, pattern, reason, SafetyAction.ESCALATE))
        for rule_id, pattern, reason in _WARN_OWNER:
            rules.append(_Rule(rule_id, pattern, reason, SafetyAction.WARN))
    else:
        for rule_id, pattern, reason in _ESCALATE_TECH:
            rules.append(_Rule(rule_id, pattern, reason, SafetyAction.BLOCK))
        for rule_id, pattern, reason in _WARN_TECH:
            rules.append(_Rule(rule_id, pattern, reason, SafetyAction.WARN))
    return rules


def assess_request(question: str, *, audience: Audience = Audience.OWNER) -> SafetyAssessment:
    """Classify a user question before LLM generation."""
    text = question.strip()
    if not text:
        return SafetyAssessment(
            action=SafetyAction.ALLOW,
            rule_id="empty",
            reason="",
            audience=audience,
        )

    best: _Rule | None = None
    for rule in _rules_for(audience):
        if rule.pattern.search(text):
            if best is None or _severity(rule.action) > _severity(best.action):
                best = rule

    if best is None:
        directive = _PROMPT_TECH if audience == Audience.TECHNICIAN else ""
        return SafetyAssessment(
            action=SafetyAction.ALLOW,
            rule_id="allow",
            reason="",
            audience=audience,
            prompt_directive=directive,
        )

    directive = ""
    if best.action == SafetyAction.ESCALATE:
        directive = _PROMPT_ESCALATE
    elif best.action == SafetyAction.WARN:
        directive = _PROMPT_WARN
    elif best.action == SafetyAction.BLOCK:
        directive = ""
    elif audience == Audience.TECHNICIAN:
        directive = _PROMPT_TECH

    return SafetyAssessment(
        action=best.action,
        rule_id=best.rule_id,
        reason=best.reason,
        audience=audience,
        prompt_directive=directive,
    )


def _severity(action: SafetyAction) -> int:
    return {
        SafetyAction.ALLOW: 0,
        SafetyAction.WARN: 1,
        SafetyAction.ESCALATE: 2,
        SafetyAction.BLOCK: 3,
    }[action]


def block_message(assessment: SafetyAssessment) -> str:
    return _BLOCK_TEMPLATE.format(reason=assessment.reason)


def escalate_message(assessment: SafetyAssessment) -> str:
    return _ESCALATION_TEMPLATE.format(reason=assessment.reason)


# Post-LLM: procedural steps an owner should not receive.
_UNSAFE_PROCEDURE = re.compile(
    r"(\bstep\s+\d+\b|\b\d+\.\s|\bthen\s+(measure|remove|replace|disconnect|test)\b)"
    r".{0,120}\b(voltage|120\s*v|panel|acu|control\s+board|multimeter|disassemble)\b",
    re.I | re.S,
)

_FORBIDDEN_OUTPUT = re.compile(
    r"\b(bypass|jumper|jump\s+the|defeat\s+the)\b.{0,40}\b(door|lock|interlock)\b",
    re.I,
)

_VOLTAGE_WARNING = re.compile(
    r"\b(voltage|120\s*v|shock|electrical\s+hazard|disconnect\s+power|unplug)\b",
    re.I,
)
