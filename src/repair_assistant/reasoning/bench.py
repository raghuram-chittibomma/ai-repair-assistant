"""Promotion gate for the published reasoning policy."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from repair_assistant.reasoning.policy import load_answer_invariants, policy_config_path
from repair_assistant.reasoning.release import apply_policy_release
from repair_assistant.reasoning.solver import check_policy, undecided_claims
from repair_assistant.reasoning.translator import Translator

FIXTURES = Path(__file__).resolve()
for _parent in FIXTURES.parents:
    _candidate = _parent / "evals" / "reasoning" / "fixtures.yaml"
    if _candidate.is_file():
        FIXTURES = _candidate
        break
else:
    FIXTURES = Path("evals") / "reasoning" / "fixtures.yaml"


@dataclass
class ScenarioResult:
    id: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


def fixtures_path() -> Path:
    return FIXTURES


def run_bench(path: Path | None = None) -> list[ScenarioResult]:
    source = path or fixtures_path()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{source} must be a mapping")
    policy = load_answer_invariants()
    results = [_version_result(raw, policy.id, policy.version)]
    results.extend(_completeness_results(policy))
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        results.append(
            ScenarioResult(
                id="scenarios",
                passed=False,
                expected="list",
                actual="missing",
                detail="scenarios must be a non-empty list",
            )
        )
        return results
    for item in scenarios:
        results.append(_scenario(policy, item))
    return results


def scorecard_markdown(
    results: list[ScenarioResult], *, title: str = "Reasoning bench", all_detail: bool = False
) -> str:
    passed = sum(1 for item in results if item.passed)
    lines = [
        f"# {title}",
        "",
        f"Policy file: `{policy_config_path()}`",
        "",
        f"{passed}/{len(results)} passed.",
        "",
        "| Scenario | Expected | Actual | Result |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        mark = "pass" if item.passed else "fail"
        shown = item.detail and (all_detail or not item.passed)
        detail = f" — {item.detail}" if shown else ""
        lines.append(f"| {item.id} | {item.expected} | {item.actual}{detail} | {mark} |")
    lines.append("")
    return "\n".join(lines)


def _version_result(raw: dict, policy_id: str, version: int) -> ScenarioResult:
    declared_id = str(raw.get("policy_id") or "")
    declared = raw.get("policy_version")
    ok = declared_id == policy_id and declared == version
    return ScenarioResult(
        id="policy-version",
        passed=ok,
        expected=f"{policy_id}@{version}",
        actual=f"{declared_id}@{declared}",
        detail="" if ok else "fixture pack does not match the published policy version",
    )


def run_translation_probe(translator: Translator, path: Path | None = None) -> list[ScenarioResult]:
    """Live translator over natural turns. A measurement, not a promotion gate."""
    source = path or fixtures_path().with_name("translation_probe.yaml")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{source} must be a mapping")
    policy = load_answer_invariants()
    results = [_version_result(raw, policy.id, policy.version)]
    for item in raw.get("cases") or []:
        case_id = str(item.get("id") or "unnamed")
        accepted = [str(value) for value in item.get("expect") or []]
        started = time.perf_counter()
        release = apply_policy_release(
            question=str(item.get("question") or ""),
            answer=str(item.get("answer") or "").strip(),
            translator=translator,
            policy=policy,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        reasoning = release.reasoning
        outcome = str(reasoning.get("outcome") or "")
        results.append(
            ScenarioResult(
                id=case_id,
                passed=outcome in accepted,
                expected=" or ".join(accepted),
                actual=outcome,
                detail=(
                    f"{elapsed} ms; premises {reasoning.get('premises') or {}}; "
                    f"claims {reasoning.get('claims') or {}}"
                    + (f"; {reasoning['reason']}" if reasoning.get("reason") else "")
                ),
            )
        )
    return results


def _completeness_results(policy) -> list[ScenarioResult]:
    """Once every user fact is known, the rules must decide each claim."""
    gaps = undecided_claims(policy)
    out: list[ScenarioResult] = []
    for var in policy.variables:
        if var.role != "claim":
            continue
        gap = gaps.get(var.name)
        out.append(
            ScenarioResult(
                id=f"decided:{var.name}",
                passed=gap is None,
                expected="decided",
                actual="decided" if gap is None else "open",
                detail="" if gap is None else f"facts {gap} leave it open",
            )
        )
    return out


def _scenario(policy, item: object) -> ScenarioResult:
    if not isinstance(item, dict):
        return ScenarioResult("invalid", False, "mapping", type(item).__name__)
    scenario_id = str(item.get("id") or "unnamed")
    expected = str(item.get("expect") or "")
    premises = item.get("premises") or {}
    claims = item.get("claims") or {}
    if not isinstance(premises, dict) or not isinstance(claims, dict):
        return ScenarioResult(scenario_id, False, expected, "bad-assignments")
    finding = check_policy(policy, premises, claims)
    expected_rules = item.get("expect_rules") or []
    if not isinstance(expected_rules, list):
        expected_rules = []
    rules_ok = set(expected_rules) == set(finding.rule_ids)
    passed = finding.outcome == expected and rules_ok
    detail = ""
    if not rules_ok:
        detail = f"rules {finding.rule_ids}"
    return ScenarioResult(
        id=scenario_id,
        passed=passed,
        expected=expected,
        actual=finding.outcome,
        detail=detail,
    )
