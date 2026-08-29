"""Safety policy tests. YAML fixtures are the single source (review R46)."""

from __future__ import annotations

import pytest

from repair_assistant.safety.bench import evaluate_fixture, load_fixtures
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import apply_owner_evidence_policy, assess_request


def _yaml_fixtures() -> list[dict]:
    return list(load_fixtures()["fixtures"])


@pytest.mark.parametrize(
    "fixture",
    _yaml_fixtures(),
    ids=lambda fixture: fixture["id"],
)
def test_safety_yaml_fixture(fixture: dict) -> None:
    result = evaluate_fixture(fixture)
    assert result.passed, result.detail


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
    assessment = assess_request("not washing properly", audience=Audience.OWNER)
    evidence = "[1] tech-sheet\nFOR SERVICE TECHNICIAN'S USE ONLY\nTEST #1: ACU"
    enriched = apply_owner_evidence_policy(assessment, evidence)
    assert "service technician" in enriched.prompt_directive.lower()
    assert enriched.action == SafetyAction.ALLOW
