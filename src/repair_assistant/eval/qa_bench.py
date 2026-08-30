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
from repair_assistant.eval.grading import grade_answer, grade_diagnose_turns
from repair_assistant.eval.groundedness import format_evidence_for_judge, score_claims
from repair_assistant.eval.llm_judge import JudgeClient, grade_with_optional_judge, needs_llm_judge
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.ingest.store import Database
from repair_assistant.qa.context import Citation
from repair_assistant.qa.generate import ask
from repair_assistant.qa.structured import Claim, claims_from_dicts


@dataclass
class TurnRecord:
    turn: int
    user_message: str
    assistant_message: str
    abstained: bool
    citations: list[str]
    retrieval_count: int
    claims: list = field(default_factory=list)
    evidence_blocks: dict[int, str] = field(default_factory=dict)
    diagnostic: dict = field(default_factory=dict)


@dataclass
class QAScenarioResult:
    scenario_id: str
    passed: bool
    detail: str = ""
    command: str = "ask"
    abstained: bool = False
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    claims: list = field(default_factory=list)
    evidence_blocks: dict[int, str] = field(default_factory=dict)
    turns: list[TurnRecord] = field(default_factory=list)
    duration_ms: int = 0
    claims_checked: int = 0
    claims_unsupported: int = 0
    groundedness_rate: float | None = None


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
            keys.append(cite.label)
            pub = cite.label.split()[0]
            if pub:
                keys.append(pub)
    return keys


def _stamp_groundedness(result: QAScenarioResult, claims: list, blocks: dict[int, str]) -> None:
    parsed: list[Claim] = []
    for item in claims or []:
        if isinstance(item, Claim):
            parsed.append(item)
        elif isinstance(item, dict):
            parsed.extend(claims_from_dicts([item]))
    report = score_claims(parsed, blocks)
    result.claims_checked = report.checked
    result.claims_unsupported = report.unsupported
    result.groundedness_rate = report.rate


def grade_scenario(scenario: dict[str, Any], result: QAScenarioResult) -> tuple[bool, str]:
    return grade_answer(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
        claims=list(getattr(result, "claims", None) or []),
        evidence_blocks=dict(getattr(result, "evidence_blocks", None) or {}),
    )


def _appliance(scenario: dict[str, Any]) -> Appliance | None:
    app = scenario.get("appliance") or {}
    model = app.get("model")
    if not model:
        return None
    return Appliance(model=model, serial=app.get("serial"))


def _run_ask(
    db: Database,
    corpus,
    scenario: dict[str, Any],
    *,
    use_judge: bool = False,
    judge_llm: JudgeClient | None = None,
) -> QAScenarioResult:
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
        claims=list(outcome.claims or []),
        evidence_blocks=dict(outcome.evidence_blocks or {}),
        duration_ms=elapsed,
    )
    _stamp_groundedness(result, result.claims, result.evidence_blocks)
    passed, detail = grade_with_optional_judge(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
        use_judge=use_judge,
        llm=judge_llm,
        deterministic_grade=grade_answer,
        evidence_text=format_evidence_for_judge(outcome.evidence_blocks),
        claims=list(outcome.claims or []),
        evidence_blocks=dict(outcome.evidence_blocks or {}),
    )
    result.passed = passed
    result.detail = detail
    return result


def _run_diagnose(
    db: Database,
    corpus,
    scenario: dict[str, Any],
    *,
    use_judge: bool = False,
    judge_llm: JudgeClient | None = None,
) -> QAScenarioResult:
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
                claims=list(getattr(last, "claims", None) or []),
                evidence_blocks=dict(getattr(last, "evidence_blocks", None) or {}),
                diagnostic=dict(getattr(last, "diagnostic", None) or {}),
            )
        )

    elapsed = int((time.perf_counter() - start) * 1000)
    if not turns:
        return QAScenarioResult(
            scenario_id=scenario["id"],
            passed=False,
            command="diagnose",
            detail="no turns recorded",
            duration_ms=elapsed,
        )

    by_turn = {t.turn: t for t in turns}
    if scenario.get("turn_grades"):
        judge_n = int(
            scenario.get("judge_turn")
            or max(int(k) for k in scenario["turn_grades"])
        )
    else:
        judge_n = int(scenario.get("expect_turn") or turns[-1].turn)
    target = by_turn.get(judge_n) or turns[-1]

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
    _stamp_groundedness(
        result,
        list(getattr(target, "claims", None) or []),
        dict(getattr(target, "evidence_blocks", None) or {}),
    )

    def _det(
        scen: dict[str, Any],
        *,
        answer: str,
        citations: list[str],
        abstained: bool,
        **_extra: Any,
    ) -> tuple[bool, str]:
        del answer, citations, abstained
        return grade_diagnose_turns(scen, turns)

    passed, detail = grade_with_optional_judge(
        scenario,
        answer=result.answer,
        citations=result.citations,
        abstained=result.abstained,
        use_judge=use_judge,
        llm=judge_llm,
        deterministic_grade=_det,
        evidence_text=format_evidence_for_judge(dict(getattr(target, "evidence_blocks", None) or {})),
        claims=list(getattr(target, "claims", None) or []),
        evidence_blocks=dict(getattr(target, "evidence_blocks", None) or {}),
    )
    # Prose judge only sees one turn; when turn_grades exist, annotate if judge skipped.
    if (
        scenario.get("turn_grades")
        and not use_judge
        and needs_llm_judge(scenario)
    ):
        detail = f"{detail}; det turns only (needs --judge for prose)"
    result.passed = passed
    result.detail = detail
    return result


def run_smoke_bench(
    db: Database,
    *,
    scenarios_path: Path | None = None,
    scenario_ids: set[str] | None = None,
    use_judge: bool = False,
    judge_llm: JudgeClient | None = None,
    eval_run_id: str | None = None,
) -> list[QAScenarioResult]:
    data = load_smoke_scenarios(scenarios_path)
    corpus = manifest_mod.load()
    results: list[QAScenarioResult] = []
    run_id = eval_run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    from repair_assistant.observability.eval_context import eval_trace_context

    for scenario in data["scenarios"]:
        if scenario_ids and scenario["id"] not in scenario_ids:
            continue
        with eval_trace_context(
            eval_bench="qa",
            eval_run_id=run_id,
            scenario_id=scenario["id"],
        ):
            if scenario.get("command") == "diagnose":
                results.append(
                    _run_diagnose(db, corpus, scenario, use_judge=use_judge, judge_llm=judge_llm)
                )
            else:
                results.append(
                    _run_ask(db, corpus, scenario, use_judge=use_judge, judge_llm=judge_llm)
                )
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
    lines = [
        "# Q&A smoke bench",
        "",
        *scorecard_repro_lines(),
        "",
        f"**{passed}/{len(results)} passed**",
        "",
    ]
    lines.append("| scenario | command | pass | ms | ungrounded | detail |")
    lines.append("| --- | --- | --- | ---: | ---: | --- |")
    for r in results:
        mark = "yes" if r.passed else "NO"
        ungrounded = (
            f"{r.claims_unsupported}/{r.claims_checked}" if r.claims_checked else "n/a"
        )
        lines.append(
            f"| {r.scenario_id} | {r.command} | {mark} | {r.duration_ms} | {ungrounded} | {r.detail} |"
        )
    rated = [r for r in results if r.groundedness_rate is not None]
    if rated:
        mean = sum(r.groundedness_rate or 0.0 for r in rated) / len(rated)
        lines.extend(
            [
                "",
                "## Groundedness (review R27)",
                "",
                f"Mean unsupported-claim rate: {mean:.2f} "
                f"(n={len(rated)} scenarios with checkable claims).",
                "Hard fail is zero token overlap between a claim and its cited block.",
                "",
            ]
        )
    else:
        lines.append("")
    return "\n".join(lines)
