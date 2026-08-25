"""Load and grade Q&A smoke scenarios."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.diagnostic.session import DiagnosticSession
from repair_assistant.eval.grading import grade_answer
from repair_assistant.ingest.store import Database
from repair_assistant.qa.context import Citation
from repair_assistant.qa.generate import ask


@dataclass
class TurnRecord:
    turn: int
    user_message: str
    assistant_message: str
    abstained: bool
    citations: list[str]
    retrieval_count: int


@dataclass
class QAScenarioResult:
    scenario_id: str
    passed: bool
    detail: str = ""
    command: str = "ask"
    abstained: bool = False
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)
    duration_ms: int = 0


def load_smoke_scenarios(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "qa" / "smoke-scenarios.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _cite_keys(citations: list[Citation]) -> list[str]:
    keys: list[str] = []
    for cite in citations:
        keys.append(cite.doc_id)
        if cite.label:
            pub = cite.label.split()[0]
            if pub:
                keys.append(pub)
    return keys


def grade_scenario(scenario: dict[str, Any], result: QAScenarioResult) -> tuple[bool, str]:
    return grade_answer(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
    )


def _appliance(scenario: dict[str, Any]) -> Appliance | None:
    app = scenario.get("appliance") or {}
    model = app.get("model")
    if not model:
        return None
    return Appliance(model=model, serial=app.get("serial"))


def _run_ask(db: Database, corpus, scenario: dict[str, Any]) -> QAScenarioResult:
    start = time.perf_counter()
    outcome = ask(
        db,
        corpus,
        scenario["question"],
        appliance=_appliance(scenario),
    )
    elapsed = int((time.perf_counter() - start) * 1000)
    cite_keys = _cite_keys(outcome.citations)
    result = QAScenarioResult(
        scenario_id=scenario["id"],
        passed=False,
        command="ask",
        abstained=outcome.abstained,
        answer=outcome.answer,
        citations=cite_keys,
        duration_ms=elapsed,
    )
    passed, detail = grade_answer(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
    )
    result.passed = passed
    result.detail = detail
    return result


def _run_diagnose(db: Database, corpus, scenario: dict[str, Any]) -> QAScenarioResult:
    start = time.perf_counter()
    session = DiagnosticSession(corpus, appliance=_appliance(scenario))
    turns: list[TurnRecord] = []
    for user_message in scenario.get("turns") or []:
        last = session.send(db, user_message)
        turns.append(
            TurnRecord(
                turn=last.turn,
                user_message=last.user_message,
                assistant_message=last.assistant_message,
                abstained=last.abstained,
                citations=_cite_keys(last.citations),
                retrieval_count=last.retrieval_count,
            )
        )

    elapsed = int((time.perf_counter() - start) * 1000)
    expect_turn = int(scenario.get("expect_turn") or (turns[-1].turn if turns else 1))
    target = next((t for t in turns if t.turn == expect_turn), turns[-1] if turns else None)
    if target is None:
        return QAScenarioResult(
            scenario_id=scenario["id"],
            passed=False,
            command="diagnose",
            detail="no turns recorded",
            duration_ms=elapsed,
        )

    result = QAScenarioResult(
        scenario_id=scenario["id"],
        passed=False,
        command="diagnose",
        abstained=target.abstained,
        answer=target.assistant_message,
        citations=target.citations,
        turns=turns,
        duration_ms=elapsed,
    )
    passed, detail = grade_answer(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
    )
    result.passed = passed
    result.detail = detail
    return result


def run_smoke_bench(
    db: Database,
    *,
    scenarios_path: Path | None = None,
    scenario_ids: set[str] | None = None,
) -> list[QAScenarioResult]:
    data = load_smoke_scenarios(scenarios_path)
    corpus = manifest_mod.load()
    results: list[QAScenarioResult] = []
    for scenario in data["scenarios"]:
        if scenario_ids and scenario["id"] not in scenario_ids:
            continue
        if scenario.get("command") == "diagnose":
            results.append(_run_diagnose(db, corpus, scenario))
        else:
            results.append(_run_ask(db, corpus, scenario))
    return results


def write_run_log(results: list[QAScenarioResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "results": [
            {
                **{k: v for k, v in asdict(r).items() if k != "turns"},
                "turns": [asdict(t) for t in r.turns],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")


def scorecard_markdown(results: list[QAScenarioResult]) -> str:
    passed = sum(1 for r in results if r.passed)
    lines = ["# Q&A smoke bench", "", f"**{passed}/{len(results)} passed**", ""]
    lines.append("| scenario | command | pass | ms | detail |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for r in results:
        mark = "yes" if r.passed else "NO"
        lines.append(f"| {r.scenario_id} | {r.command} | {mark} | {r.duration_ms} | {r.detail} |")
    lines.append("")
    return "\n".join(lines)
