"""Score deterministic safety policy against evals/safety/fixtures.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import assess_request


@dataclass
class SafetyBenchResult:
    fixture_id: str
    passed: bool
    hard: bool
    detail: str = ""
    role: str = ""
    observed: str = ""
    expect_action: str = ""


@dataclass
class AdversarialSummary:
    """Held-out rates (review R4). Not a CI gate."""

    results: list[SafetyBenchResult]
    unsafe_total: int
    unsafe_caught: int
    benign_total: int
    false_escalations: int

    @property
    def unsafe_recall(self) -> float:
        return self.unsafe_caught / self.unsafe_total if self.unsafe_total else 0.0

    @property
    def false_escalation_rate(self) -> float:
        return self.false_escalations / self.benign_total if self.benign_total else 0.0


def load_fixtures(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "safety" / "fixtures.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def evaluate_fixture(fixture: dict[str, Any]) -> SafetyBenchResult:
    """Grade one YAML fixture — shared by the bench and the unit suite (R46)."""
    audience = Audience(fixture.get("audience") or "owner")
    assessment = assess_request(fixture["question"], audience=audience)
    expected = SafetyAction(fixture["expect_action"])
    passed = assessment.action == expected
    detail = f"got {assessment.action.value} ({assessment.rule_id})"
    if not passed:
        detail = f"expected {expected.value}; {detail}"

    if passed and fixture.get("sample_answer"):
        gated = gate_answer(
            assessment,
            fixture["sample_answer"],
            evidence_text=fixture.get("sample_evidence") or "",
        )
        gate_expected = SafetyAction(fixture["sample_gate_action"])
        if gated.action != gate_expected:
            passed = False
            detail = f"gate expected {gate_expected.value}, got {gated.action.value}"
        for forbidden in fixture.get("sample_must_not_contain") or []:
            if forbidden.lower() in gated.text.lower():
                passed = False
                detail = f"gate output still contains {forbidden!r}"
        must_any = fixture.get("sample_must_contain_any") or []
        if must_any and not any(m.lower() in gated.text.lower() for m in must_any):
            passed = False
            detail = f"gate output missing any of {must_any!r}"

    return SafetyBenchResult(
        fixture_id=str(fixture["id"]),
        passed=passed,
        hard=bool(fixture.get("hard")),
        detail=detail,
        role=str(fixture.get("role") or ""),
        observed=assessment.action.value,
        expect_action=expected.value,
    )


def run_bench(*, fixtures_path: Path | None = None) -> list[SafetyBenchResult]:
    data = load_fixtures(fixtures_path)
    return [evaluate_fixture(fixture) for fixture in data["fixtures"]]


def load_adversarial(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "safety" / "adversarial.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def run_adversarial(*, fixtures_path: Path | None = None) -> AdversarialSummary:
    """Score the held-out set. Do not use this to retune policy.py."""
    data = load_adversarial(fixtures_path)
    results = [evaluate_fixture(fixture) for fixture in data["fixtures"]]
    unsafe = [r for r in results if r.role == "unsafe"]
    benign = [r for r in results if r.role == "benign"]
    caught = sum(1 for r in unsafe if r.observed != SafetyAction.ALLOW.value)
    false_esc = sum(
        1
        for r in benign
        if r.observed in {SafetyAction.ESCALATE.value, SafetyAction.BLOCK.value}
    )
    return AdversarialSummary(
        results=results,
        unsafe_total=len(unsafe),
        unsafe_caught=caught,
        benign_total=len(benign),
        false_escalations=false_esc,
    )


def scorecard_markdown(
    results: list[SafetyBenchResult],
    *,
    adversarial: AdversarialSummary | None = None,
) -> str:
    lines = ["# Safety policy bench", "", *scorecard_repro_lines(), ""]
    passed = sum(1 for r in results if r.passed)
    lines.append(f"**{passed}/{len(results)} passed**")
    lines.append("")
    lines.append("| fixture | hard | pass | detail |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        mark = "yes" if r.passed else "NO"
        hard = "yes" if r.hard else ""
        lines.append(f"| {r.fixture_id} | {hard} | {mark} | {r.detail} |")
    if adversarial is not None:
        lines.extend(
            [
                "",
                "## Adversarial held-out (R4)",
                "",
                "Not a CI gate. Authored before policy edits.",
                "",
                f"- **Unsafe-recall:** {adversarial.unsafe_caught}/"
                f"{adversarial.unsafe_total} "
                f"({adversarial.unsafe_recall:.0%})",
                f"- **False-escalation:** {adversarial.false_escalations}/"
                f"{adversarial.benign_total} "
                f"({adversarial.false_escalation_rate:.0%})",
                "",
                "| fixture | role | expected | observed |",
                "| --- | --- | --- | --- |",
            ]
        )
        for r in adversarial.results:
            lines.append(
                f"| {r.fixture_id} | {r.role} | {r.expect_action} | {r.observed} |"
            )
    lines.append("")
    return "\n".join(lines)
