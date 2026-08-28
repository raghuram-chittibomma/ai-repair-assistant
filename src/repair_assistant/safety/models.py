"""Safety models and audience tiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Audience(StrEnum):
    OWNER = "owner"
    TECHNICIAN = "technician"


class SafetyAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    ESCALATE = "escalate"
    BLOCK = "block"


@dataclass(frozen=True)
class SafetyAssessment:
    action: SafetyAction
    rule_id: str
    reason: str
    audience: Audience
    prompt_directive: str = ""


@dataclass
class SafetyGateResult:
    text: str
    action: SafetyAction
    rule_id: str
    notice: str = ""
    escalated: bool = False
    blocked: bool = False
