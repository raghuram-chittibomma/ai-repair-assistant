"""Deterministic repair-risk rules — the LLM is not the sole safety authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from repair_assistant.prompts import safety_escalate, safety_technician, safety_warn
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment

# Ordered highest-severity first within each audience.
_BLOCK = [
    (
        "bypass-interlock",
        re.compile(
            r"\b(bypass|jumper|jump|defeat|disable|override|tape\s+over)\b.{0,40}"
            r"\b(door|lock|interlock|lid|safety\s+switch)\b"
            r"|\b(door|lock|interlock|lid|safety\s+switch)\b.{0,40}"
            r"\b(bypass|jumper|jump|defeat|disable|override)\b",
            re.I,
        ),
        "Requests to bypass or defeat door or lid interlocks are not provided.",
    ),
    (
        "defeat-safety-device",
        re.compile(
            r"\b(defeat|disable|remove|bypass)\b.{0,40}\b(safety|interlock|thermal\s+fuse)\b"
            r"|\brun\s+without\b.{0,20}\b(door|lid|interlock)\b",
            re.I,
        ),
        "Requests to defeat safety devices are not provided.",
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
    (
        "service-test-procedure",
        re.compile(
            r"\bTEST\s*#\s*\d+\b.{0,60}\b(step|steps|perform|run|do|how|procedure)\b"
            r"|\b(how|steps?|perform|run)\b.{0,60}\bTEST\s*#\s*\d+\b",
            re.I,
        ),
        "Diagnostic TEST procedures require qualified appliance service personnel.",
    ),
    (
        "stored-energy",
        re.compile(
            r"\b(discharge|bleed)\b.{0,30}\bcapacitor\b"
            r"|\bcapacitor\b.{0,40}\b(discharge|shock|stored\s+energy)\b",
            re.I,
        ),
        "Capacitor discharge and stored-energy work require qualified service.",
    ),
    (
        "tip-over-service",
        re.compile(
            r"\b(tip|lay|turn|place)\b.{0,25}\b(washer|dryer|machine|appliance)\b"
            r".{0,40}\b(on\s+(its\s+)?(side|back)|upside\s*down)\b",
            re.I,
        ),
        "Tipping or laying the appliance for service requires qualified handling.",
    ),
    (
        "water-line-mod",
        re.compile(
            r"\b(cut|drill|splice|modify)\b.{0,30}\b(drain\s+hose|inlet\s+hose|water\s+line)\b"
            r"|\b(drain\s+hose|inlet\s+hose)\b.{0,30}\b(cut|drill|splice|modify)\b",
            re.I,
        ),
        "Modifying water or drain lines can cause flooding and requires qualified service.",
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
    (
        "defeat-safety-device",
        _BLOCK[1][1],
        _BLOCK[1][2],
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

# Evidence looks like service literature / tech-only procedures (G1).
_SERVICE_EVIDENCE = re.compile(
    r"FOR\s+SERVICE\s+TECHNICIAN"
    r"|\bTEST\s*#\s*\d+\b"
    r"|\blive\s+voltage\b"
    r"|\btech[\s_-]?sheet\b"
    r"|\bservice\s+manual\b",
    re.I,
)

_OWNER_SERVICE_LIT_DIRECTIVE = (
    "Audience: appliance owner. Evidence may include service technician "
    "literature. You may share owner-safe checks (load, detergent, cycle, "
    "visible leaks, error codes on the display). Do NOT quote step-by-step "
    "TEST # procedures, live-voltage measurements, panel removal, or "
    "control-board work. For those, briefly say a qualified technician is "
    "required and cite the evidence category only if needed."
)

# Post-LLM: procedural steps an owner should not receive.
_UNSAFE_PROCEDURE = re.compile(
    r"(\bstep\s+\d+\b|\b\d+\.\s|\bthen\s+(measure|remove|replace|disconnect|test)\b)"
    r".{0,120}\b(voltage|120\s*v|panel|acu|control\s+board|multimeter|disassemble)\b",
    re.I | re.S,
)

# Owner answers must not walk through diagnostic TEST procedures.
_OWNER_TECH_PROCEDURE_OUTPUT = re.compile(
    r"\bTEST\s*#\s*\d+\b.{0,240}\b(\d+\.\s|step\s+\d+|measure|multimeter|VAC|120\s*v)\b"
    r"|\b(measure|multimeter)\b.{0,60}\b(VAC|voltage|120\s*v|240\s*v)\b",
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

_CITE_REF = re.compile(r"\[\d+\]")
# Numbered checklists / explicit service steps need a citation (G3).
_GROUNDED_PROCEDURE = re.compile(
    r"(?:^|\n)\s*\d+\.\s+\S.{8,}"
    r"|\bstep\s+\d+\b"
    r"|\b(measure|multimeter|remove the|replace the|disconnect the)\b",
    re.I,
)

_UNGROUNDED_ABSTAIN = (
    "ABSTAIN: Procedural guidance must cite manufacturer evidence with [n] "
    "references; none were present in the draft answer."
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
        directive = safety_technician() if audience == Audience.TECHNICIAN else ""
        return SafetyAssessment(
            action=SafetyAction.ALLOW,
            rule_id="allow",
            reason="",
            audience=audience,
            prompt_directive=directive,
        )

    directive = ""
    if best.action == SafetyAction.ESCALATE:
        directive = safety_escalate()
    elif best.action == SafetyAction.WARN:
        directive = safety_warn()
    elif best.action == SafetyAction.BLOCK:
        directive = ""
    elif audience == Audience.TECHNICIAN:
        directive = safety_technician()

    return SafetyAssessment(
        action=best.action,
        rule_id=best.rule_id,
        reason=best.reason,
        audience=audience,
        prompt_directive=directive,
    )


def evidence_looks_like_service_literature(evidence_text: str) -> bool:
    """True when retrieved evidence includes technician-oriented markers."""
    return bool(_SERVICE_EVIDENCE.search(evidence_text or ""))


def apply_owner_evidence_policy(
    assessment: SafetyAssessment,
    evidence_text: str,
) -> SafetyAssessment:
    """G1: when owners receive service literature, add a hard prompt directive."""
    if assessment.audience != Audience.OWNER:
        return assessment
    if assessment.action == SafetyAction.BLOCK:
        return assessment
    if not evidence_looks_like_service_literature(evidence_text):
        return assessment

    existing = (assessment.prompt_directive or "").strip()
    if _OWNER_SERVICE_LIT_DIRECTIVE in existing:
        return assessment
    directive = (
        f"{existing}\n\n{_OWNER_SERVICE_LIT_DIRECTIVE}".strip()
        if existing
        else _OWNER_SERVICE_LIT_DIRECTIVE
    )
    return replace(assessment, prompt_directive=directive)


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


#: Longest span any hazard pattern below can match, from its bounded `.{0,N}`
#: gaps plus the surrounding literals. The streaming gate uses this to size its
#: hold-back window (see `safety/stream_gate.py`).
MAX_HAZARD_MATCH_CHARS = 320


def output_hazard(assessment: SafetyAssessment, answer: str) -> str | None:
    """Rule id of the first output hazard in `answer`, or None.

    The single definition of "this generated text is hazardous", shared by the
    post-LLM gate (`safety.gate.gate_answer`) and the incremental streaming gate.
    Keeping one copy is deliberate: two of these would drift, and the drift would
    be silent in exactly the direction that matters.

    Only output-dependent *hazard* branches belong here. The grounding check (G3)
    is deliberately excluded — it is not monotone in the answer text, because a
    procedure that lacks a citation now may gain one before the answer ends.
    """
    text = (answer or "").strip()
    if not text:
        return None
    if _FORBIDDEN_OUTPUT.search(text):
        return "output-bypass"
    if assessment.audience == Audience.OWNER:
        if _OWNER_TECH_PROCEDURE_OUTPUT.search(text):
            return "owner-tech-procedure"
        if assessment.action == SafetyAction.ESCALATE and _UNSAFE_PROCEDURE.search(text):
            return assessment.rule_id
    return None


def needs_grounding_citation(answer: str) -> bool:
    """True when the answer looks procedural but has no [n] citation (G3)."""
    text = (answer or "").strip()
    if not text:
        return False
    upper = text.upper()
    if upper.startswith(("ABSTAIN:", "BLOCK:", "ESCALATE:")):
        return False
    if _CITE_REF.search(text):
        return False
    return bool(_GROUNDED_PROCEDURE.search(text))
