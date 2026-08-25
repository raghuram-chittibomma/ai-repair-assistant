"""Unit tests for Phase 7 safety policy and gates."""

from __future__ import annotations

from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import assess_request


def test_bypass_blocked_for_owner() -> None:
    assessment = assess_request(
        "How do I bypass the door lock on my washer?",
        audience=Audience.OWNER,
    )
    assert assessment.action == SafetyAction.BLOCK


def test_bypass_blocked_for_technician() -> None:
    assessment = assess_request(
        "How do I bypass the door lock for testing?",
        audience=Audience.TECHNICIAN,
    )
    assert assessment.action == SafetyAction.BLOCK


def test_voltage_escalates_for_owner() -> None:
    assessment = assess_request(
        "How do I measure voltage on the door lock?",
        audience=Audience.OWNER,
    )
    assert assessment.action == SafetyAction.ESCALATE


def test_visual_check_allowed_for_owner() -> None:
    assessment = assess_request(
        "What should I check if the door won't close?",
        audience=Audience.OWNER,
    )
    assert assessment.action == SafetyAction.ALLOW


def test_technician_voltage_warns_not_escalates() -> None:
    assessment = assess_request(
        "What are the voltage measurement steps for TEST #4?",
        audience=Audience.TECHNICIAN,
    )
    assert assessment.action == SafetyAction.WARN


def test_gate_strips_unsafe_procedure_for_owner() -> None:
    assessment = assess_request(
        "How do I measure live voltage?",
        audience=Audience.OWNER,
    )
    raw = "Step 1: Set multimeter to volts. Step 2: Measure voltage at the lock with power on."
    gated = gate_answer(assessment, raw)
    assert gated.escalated
    assert "step 1" not in gated.text.lower()
    assert "multimeter" not in gated.text.lower()


def test_gate_blocks_bypass_in_output() -> None:
    assessment = assess_request("What is F5E2?", audience=Audience.OWNER)
    raw = "You can bypass the door lock by jumpering the interlock."
    gated = gate_answer(assessment, raw)
    assert gated.blocked
    assert gated.action == SafetyAction.BLOCK
