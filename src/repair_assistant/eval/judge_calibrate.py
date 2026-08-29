"""Offline / manual LLM-judge calibration pack (E10)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.llm_judge import JudgeClient, JudgeVerdict, judge_answer


@dataclass
class CalibrationCaseResult:
    case_id: str
    expected_passed: bool
    actual_passed: bool
    reason: str
    agreed: bool


def load_calibration(path: Path | None = None) -> list[dict[str, Any]]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "qa" / "judge-calibration.yaml")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    cases = list(data.get("cases") or [])
    if not cases:
        raise ValueError(f"no calibration cases in {path}")
    return cases


def _scenario_from_case(case: dict[str, Any]) -> dict[str, Any]:
    scen: dict[str, Any] = {
        "id": case["id"],
        "question": case.get("question") or "",
    }
    if case.get("expect"):
        scen["expect"] = case["expect"]
    if case.get("fails_if"):
        scen["fails_if"] = case["fails_if"]
    return scen


def run_calibration(
    cases: list[dict[str, Any]] | None = None,
    *,
    llm: JudgeClient,
    path: Path | None = None,
) -> list[CalibrationCaseResult]:
    """Score frozen answer+criteria cases with an LLM (or FakeJudge). No DB."""
    cases = cases if cases is not None else load_calibration(path)
    results: list[CalibrationCaseResult] = []
    for case in cases:
        expected = bool(case["expected_passed"])
        verdict: JudgeVerdict = judge_answer(
            _scenario_from_case(case),
            answer=str(case.get("answer") or ""),
            citations=list(case.get("citations") or []),
            abstained=bool(case.get("abstained", False)),
            llm=llm,
        )
        results.append(
            CalibrationCaseResult(
                case_id=case["id"],
                expected_passed=expected,
                actual_passed=verdict.passed,
                reason=verdict.reason,
                agreed=verdict.passed == expected,
            )
        )
    return results


def scorecard_markdown(results: list[CalibrationCaseResult]) -> str:
    agreed = sum(1 for r in results if r.agreed)
    from repair_assistant.eval.repro import scorecard_repro_lines

    lines = [
        "# Judge calibration",
        "",
        *scorecard_repro_lines(),
        "",
        f"**{agreed}/{len(results)} agreed** with expected_passed",
        "",
        "| case | expected | actual | agree | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        mark = "yes" if r.agreed else "NO"
        reason = r.reason.replace("|", "\\|")
        lines.append(
            f"| {r.case_id} | {r.expected_passed} | {r.actual_passed} | {mark} | {reason} |"
        )
    lines.append("")
    return "\n".join(lines)
