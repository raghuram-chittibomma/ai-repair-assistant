"""Score deterministic safety policy against evals/safety/fixtures.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import assess_request


@dataclass
class SafetyBenchResult:
    fixture_id: str
    passed: bool
    hard: bool
    detail: str = ""


def load_fixtures(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "safety" / "fixtures.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def run_bench(*, fixtures_path: Path | None = None) -> list[SafetyBenchResult]:
    data = load_fixtures(fixtures_path)
    results: list[SafetyBenchResult] = []
    for fixture in data["fixtures"]:
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

        results.append(
            SafetyBenchResult(
                fixture_id=fixture["id"],
                passed=passed,
                hard=bool(fixture.get("hard")),
                detail=detail,
            )
        )
    return results


def scorecard_markdown(results: list[SafetyBenchResult]) -> str:
    lines = ["# Safety policy bench", ""]
    passed = sum(1 for r in results if r.passed)
    lines.append(f"**{passed}/{len(results)} passed**")
    lines.append("")
    lines.append("| fixture | hard | pass | detail |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        mark = "yes" if r.passed else "NO"
        hard = "yes" if r.hard else ""
        lines.append(f"| {r.fixture_id} | {hard} | {mark} | {r.detail} |")
    lines.append("")
    return "\n".join(lines)
