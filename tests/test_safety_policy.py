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


def test_owner_test_procedure_escalates() -> None:
    assessment = assess_request(
        "How do I perform TEST #1 ACU Power Check step by step?",
        audience=Audience.OWNER,
    )
    assert assessment.action == SafetyAction.ESCALATE
    assert assessment.rule_id == "service-test-procedure"


def test_defeat_safety_blocked() -> None:
    assessment = assess_request(
        "How do I defeat the safety switch so it runs with the door open?",
        audience=Audience.OWNER,
    )
    assert assessment.action == SafetyAction.BLOCK


def test_gate_owner_tech_procedure_output() -> None:
    assessment = assess_request("not washing properly", audience=Audience.OWNER)
    raw = (
        "Run TEST #6 Water Inlet Valves: 1. Measure VAC at the valve. "
        "2. Use a multimeter with power on."
    )
    gated = gate_answer(assessment, raw)
    assert gated.escalated
    assert gated.action == SafetyAction.ESCALATE
    assert "multimeter" not in gated.text.lower()


def test_gate_ungrounded_procedure_abstains() -> None:
    assessment = assess_request("not washing properly", audience=Audience.OWNER)
    raw = (
        "1. Verify that the load is not bunched.\n"
        "2. Ensure you are using HE detergent.\n"
        "3. Confirm the correct wash cycle."
    )
    gated = gate_answer(assessment, raw)
    assert gated.blocked
    assert gated.text.upper().startswith("ABSTAIN:")
    assert "HE detergent" not in gated.text


def test_gate_allows_cited_checklist() -> None:
    assessment = assess_request("not washing properly", audience=Audience.OWNER)
    raw = (
        'From "Not cleaning clothes" [1]:\n'
        "1. Verify that the load is not bunched.\n"
        "2. Ensure you are using HE detergent."
    )
    gated = gate_answer(assessment, raw)
    assert not gated.blocked
    assert "HE detergent" in gated.text


def test_owner_service_evidence_adds_directive() -> None:
    from repair_assistant.safety.policy import apply_owner_evidence_policy

    assessment = assess_request("not washing properly", audience=Audience.OWNER)
    evidence = "[1] tech-sheet\nFOR SERVICE TECHNICIAN'S USE ONLY\nTEST #1: ACU"
    enriched = apply_owner_evidence_policy(assessment, evidence)
    assert "service technician" in enriched.prompt_directive.lower()
    assert enriched.action == SafetyAction.ALLOW
