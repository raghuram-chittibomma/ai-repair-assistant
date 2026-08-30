"""Run live ask()/diagnose against ready scenarios from candidates.yaml."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.eval.grading import grade_answer
from repair_assistant.eval.groundedness import format_evidence_for_judge
from repair_assistant.eval.llm_judge import JudgeClient, grade_with_optional_judge
from repair_assistant.eval.qa_bench import (
    QAScenarioResult,
    TurnRecord,
    _cite_keys,
    _run_diagnose,
)
from repair_assistant.ingest.store import Database
from repair_assistant.qa.generate import ask


@dataclass
class CandidateBenchResult:
    scenario_id: str
    family_id: str
    passed: bool
    skipped: bool = False
    detail: str = ""
    command: str = "ask"
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    abstained: bool = False
    duration_ms: int = 0
    turns: list[TurnRecord] = field(default_factory=list)


def load_candidates(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "scenarios" / "candidates.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_grading_overlay(path: Path | None = None) -> dict[str, dict[str, Any]]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "qa" / "candidates-grading.yaml")
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("scenarios") or {}


def _merge_scenario(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key == "id":
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = list(merged[key]) + value
        else:
            merged[key] = value
    return merged


def iter_runnable(data: dict[str, Any], *, grading: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for family in data.get("families") or []:
        for scenario in family.get("scenarios") or []:
            if scenario.get("status") != "ready":
                continue
            is_diagnose = scenario.get("command") == "diagnose"
            if is_diagnose:
                if not scenario.get("turns"):
                    continue
            elif not scenario.get("question"):
                continue
            merged = _merge_scenario(scenario, grading.get(scenario["id"], {}))
            merged["_family_id"] = family["id"]
            out.append(merged)
    return out


def _appliance(scenario: dict[str, Any]) -> Appliance | None:
    app = scenario.get("appliance") or {}
    model = app.get("model")
    if not model:
        return None
    return Appliance(
        model=model,
        serial=app.get("serial"),
        model_introduced=app.get("model_introduced"),
    )


def run_candidates_bench(
    db: Database,
    *,
    candidates_path: Path | None = None,
    grading_path: Path | None = None,
    scenario_ids: set[str] | None = None,
    use_judge: bool = False,
    judge_llm: JudgeClient | None = None,
    eval_run_id: str | None = None,
) -> list[CandidateBenchResult]:
    from datetime import UTC, datetime

    from repair_assistant.observability.eval_context import eval_trace_context

    data = load_candidates(candidates_path)
    grading = load_grading_overlay(grading_path)
    corpus = manifest_mod.load()
    results: list[CandidateBenchResult] = []
    run_id = eval_run_id or f"candidates-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

    for scenario in iter_runnable(data, grading=grading):
        if scenario_ids and scenario["id"] not in scenario_ids:
            continue

        with eval_trace_context(
            eval_bench="candidates",
            eval_run_id=run_id,
            scenario_id=scenario["id"],
        ):
            if scenario.get("command") == "diagnose":
                qa = _run_diagnose(
                    db,
                    corpus,
                    scenario,
                    use_judge=use_judge,
                    judge_llm=judge_llm,
                )
                detail = qa.detail
                if scenario.get("requires_judge") and not use_judge:
                    if "needs --judge" not in detail:
                        detail = f"{detail}; det-only (needs --judge for prose)"
                results.append(
                    CandidateBenchResult(
                        scenario_id=scenario["id"],
                        family_id=scenario["_family_id"],
                        passed=qa.passed,
                        detail=detail,
                        command="diagnose",
                        answer=qa.answer,
                        citations=qa.citations,
                        abstained=qa.abstained,
                        duration_ms=qa.duration_ms,
                        turns=qa.turns,
                    )
                )
                continue

            start = time.perf_counter()
            outcome = ask(
                db,
                corpus,
                scenario["question"],
                appliance=_appliance(scenario),
            )
            elapsed = int((time.perf_counter() - start) * 1000)
            cite_keys = _cite_keys(outcome.citations)
            passed, detail = grade_with_optional_judge(
                scenario,
                answer=outcome.answer,
                citations=cite_keys,
                abstained=outcome.abstained,
                use_judge=use_judge,
                llm=judge_llm,
                deterministic_grade=grade_answer,
                evidence_text=format_evidence_for_judge(outcome.evidence_blocks),
                claims=list(outcome.claims or []),
                evidence_blocks=dict(outcome.evidence_blocks or {}),
            )
            if scenario.get("requires_judge") and not use_judge:
                detail = f"{detail}; det-only (needs --judge for prose)"
            results.append(
                CandidateBenchResult(
                    scenario_id=scenario["id"],
                    family_id=scenario["_family_id"],
                    passed=passed,
                    detail=detail,
                    command="ask",
                    answer=outcome.answer,
                    citations=cite_keys,
                    abstained=outcome.abstained,
                    duration_ms=elapsed,
                )
            )
    return results


def scorecard_markdown(results: list[CandidateBenchResult]) -> str:
    runnable = [r for r in results if not r.skipped]
    passed = sum(1 for r in runnable if r.passed)
    from repair_assistant.eval.repro import scorecard_repro_lines

    lines = [
        "# Candidate scenarios bench",
        "",
        *scorecard_repro_lines(),
        "",
        f"**{passed}/{len(runnable)} passed**",
        "",
    ]
    lines.append("| scenario | family | pass | ms | detail |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for r in results:
        mark = "skip" if r.skipped else ("yes" if r.passed else "NO")
        lines.append(
            f"| {r.scenario_id} | {r.family_id} | {mark} | {r.duration_ms} | {r.detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def to_qa_results(results: list[CandidateBenchResult]) -> list[QAScenarioResult]:
    return [
        QAScenarioResult(
            scenario_id=r.scenario_id,
            passed=r.passed,
            detail=r.detail,
            command=r.command,
            abstained=r.abstained,
            answer=r.answer,
            citations=r.citations,
            turns=r.turns,
            duration_ms=r.duration_ms,
        )
        for r in results
        if not r.skipped
    ]
