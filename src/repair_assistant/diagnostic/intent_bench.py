"""Bake-off: OpenAI vs Jev vs regex for diagnose retrieve labels (ADR-0054)."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.diagnostic.intent import (
    build_classify_user_prompt,
    parse_diagnose_label,
)
from repair_assistant.diagnostic.jev import (
    build_classify_state,
    decide,
    jev_api_key,
    jev_decide_url,
    jev_min_confidence,
    jev_model,
    parse_retrieve_label_answer,
)
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.prompts import diagnose_intent
from repair_assistant.qa.acks import is_ack_only_message, is_unresolved_followup
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.qa.structured import DIAGNOSE_INTENT_LABELS

#: Published gpt-4o-mini list prices (USD / 1M tokens). Scorecard stamps the rate.
OPENAI_INPUT_USD_PER_MTOK = 0.15
OPENAI_OUTPUT_USD_PER_MTOK = 0.60
#: TypeSafe list price for Jev input tokens on the official API (output free).
#: Hosted ``jv_live_`` mirror is $0.42/M; direct ``api.typesafe.ai`` is $0.042/M.
#: Used when usage omits ``cost_usd`` (``/v1/systemone`` returns tokens only).
JEV_INPUT_USD_PER_MTOK = 0.042


@dataclass
class CaseResult:
    fixture_id: str
    expected: str
    predicted: str | None
    latency_ms: float
    error: str = ""
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


@dataclass
class ArmSummary:
    name: str
    results: list[CaseResult] = field(default_factory=list)
    skipped: str = ""
    cost_note: str = ""

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def mean_latency_ms(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.latency_ms for r in self.results) / len(self.results)

    @property
    def total_cost_usd(self) -> float | None:
        costs = [r.cost_usd for r in self.results if r.cost_usd is not None]
        if not costs:
            return None
        return sum(costs)

    @property
    def mean_cost_usd(self) -> float | None:
        total = self.total_cost_usd
        if total is None or not self.results:
            return None
        n_costed = sum(1 for r in self.results if r.cost_usd is not None)
        if not n_costed:
            return None
        return total / n_costed


def load_fixtures(path: Path | None = None) -> list[dict[str, Any]]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "diagnose" / "intent-fixtures.yaml")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    fixtures = list(data.get("fixtures") or [])
    if not fixtures:
        raise ValueError(f"no fixtures in {path}")
    return fixtures


def regex_diagnose_label(*, board_text: str, transcript: str) -> str | None:
    """acks.py baseline — only ack / still_unresolved; else miss."""
    del board_text
    latest = ""
    for line in reversed((transcript or "").splitlines()):
        stripped = line.strip()
        if stripped.lower().startswith("user:"):
            latest = stripped.split(":", 1)[1].strip()
            break
    if not latest:
        latest = (
            (transcript or "").strip().splitlines()[-1].strip() if transcript else ""
        )
    if is_ack_only_message(latest):
        return "ack"
    if is_unresolved_followup(latest):
        return "still_unresolved"
    return None


def _openai_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1_000_000) * OPENAI_INPUT_USD_PER_MTOK + (
        completion_tokens / 1_000_000
    ) * OPENAI_OUTPUT_USD_PER_MTOK


def _jev_cost_usd(*, cost_usd: float | None, input_tokens: int | None) -> float | None:
    if cost_usd is not None:
        return float(cost_usd)
    if input_tokens is None:
        return None
    return (input_tokens / 1_000_000) * JEV_INPUT_USD_PER_MTOK


def _format_usd(value: float | None) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "0"
    if value < 0.0001:
        return f"{value:.6f}"
    if value < 0.01:
        return f"{value:.4f}"
    return f"{value:.4f}"


def _run_openai_arm(fixtures: list[dict[str, Any]]) -> ArmSummary:
    try:
        key = openai_api_key()
    except RuntimeError:
        return ArmSummary(name="openai", skipped="OPENAI_API_KEY unset")
    if not key:
        return ArmSummary(name="openai", skipped="OPENAI_API_KEY unset")

    from repair_assistant.qa.generate import OpenAIClient

    client = OpenAIClient(
        api_key=key,
        model=llm_model(),
        prompt_name="diagnose_intent",
        max_tokens=40,
    )
    system = diagnose_intent()
    arm = ArmSummary(
        name="openai",
        cost_note=(
            f"estimated @ ${OPENAI_INPUT_USD_PER_MTOK}/M in + "
            f"${OPENAI_OUTPUT_USD_PER_MTOK}/M out"
        ),
    )
    for fix in fixtures:
        board = str(fix.get("board") or "")
        transcript = str(fix.get("transcript") or "")
        expected = str(fix.get("label") or "").strip()
        fid = str(fix.get("id") or expected)
        user = build_classify_user_prompt(board_text=board, transcript=transcript)
        t0 = time.perf_counter()
        error = ""
        predicted: str | None = None
        cost: float | None = None
        in_tok: int | None = None
        out_tok: int | None = None
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            response = client._create(messages, stream=False)
            raw = (response.choices[0].message.content or "").strip()
            predicted = parse_diagnose_label(raw)
            usage = getattr(response, "usage", None)
            if usage is not None:
                in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
                out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
                cost = _openai_cost_usd(in_tok, out_tok)
        except Exception as exc:  # noqa: BLE001 — bench must continue
            error = str(exc)[:200]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        arm.results.append(
            CaseResult(
                fixture_id=fid,
                expected=expected,
                predicted=predicted,
                latency_ms=latency_ms,
                error=error,
                cost_usd=cost,
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
        )
    return arm


def _run_jev_arm(fixtures: list[dict[str, Any]]) -> ArmSummary:
    if not jev_api_key():
        return ArmSummary(name="jev", skipped="JEV_API_KEY unset")
    arm = ArmSummary(
        name="jev",
        cost_note=(
            f"estimated @ ${JEV_INPUT_USD_PER_MTOK}/M in "
            "(usage.cost_usd when present)"
        ),
    )
    floor = jev_min_confidence()
    for fix in fixtures:
        board = str(fix.get("board") or "")
        transcript = str(fix.get("transcript") or "")
        expected = str(fix.get("label") or "").strip()
        fid = str(fix.get("id") or expected)
        state = build_classify_state(board_text=board, transcript=transcript)
        t0 = time.perf_counter()
        error = ""
        predicted: str | None = None
        cost: float | None = None
        in_tok: int | None = None
        try:
            payload = decide(state)
            predicted = parse_retrieve_label_answer(payload, min_confidence=floor)
            usage = payload.get("usage") or {}
            raw_cost = None
            if isinstance(usage, dict):
                if usage.get("cost_usd") is not None:
                    raw_cost = float(usage["cost_usd"])
                raw_tok = usage.get("input_tokens")
                if raw_tok is not None:
                    in_tok = int(raw_tok)
            cost = _jev_cost_usd(cost_usd=raw_cost, input_tokens=in_tok)
            if predicted is None:
                error = "no usable label"
        except Exception as exc:  # noqa: BLE001 — bench must continue
            error = str(exc)[:200]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        arm.results.append(
            CaseResult(
                fixture_id=fid,
                expected=expected,
                predicted=predicted,
                latency_ms=latency_ms,
                error=error,
                cost_usd=cost,
                input_tokens=in_tok,
            )
        )
    return arm


def _run_regex_arm(fixtures: list[dict[str, Any]]) -> ArmSummary:
    arm = ArmSummary(name="regex", cost_note="local / $0")
    for fix in fixtures:
        board = str(fix.get("board") or "")
        transcript = str(fix.get("transcript") or "")
        expected = str(fix.get("label") or "").strip()
        fid = str(fix.get("id") or expected)
        t0 = time.perf_counter()
        predicted = regex_diagnose_label(board_text=board, transcript=transcript)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        arm.results.append(
            CaseResult(
                fixture_id=fid,
                expected=expected,
                predicted=predicted,
                latency_ms=latency_ms,
                cost_usd=0.0,
            )
        )
    return arm


def run_bakeoff(
    *,
    fixtures_path: Path | None = None,
    arms: list[str] | None = None,
) -> list[ArmSummary]:
    fixtures = load_fixtures(fixtures_path)
    want = {a.strip().lower() for a in (arms or ["openai", "jev", "regex"])}
    summaries: list[ArmSummary] = []
    if "openai" in want:
        summaries.append(_run_openai_arm(fixtures))
    if "jev" in want:
        summaries.append(_run_jev_arm(fixtures))
    if "regex" in want:
        summaries.append(_run_regex_arm(fixtures))
    return summaries


def _confusion_lines(arm: ArmSummary) -> list[str]:
    if arm.skipped or not arm.results:
        return []
    lines = [
        "",
        f"### Confusion ({arm.name})",
        "",
        "| expected \\ predicted | count |",
        "| --- | ---: |",
    ]
    counts: Counter[str] = Counter()
    for r in arm.results:
        pred = r.predicted if r.predicted is not None else "(none)"
        counts[f"{r.expected} → {pred}"] += 1
    for key, n in sorted(counts.items()):
        lines.append(f"| `{key}` | {n} |")
    return lines


def scorecard_markdown(arms: list[ArmSummary]) -> str:
    lines = [
        "# Diagnose intent bake-off",
        "",
        "Closed-set retrieve labels (ADR-0039). Candidate classifiers for ADR-0054.",
        "",
        "## Repro",
        "",
        *scorecard_repro_lines(),
        f"- JEV_MODEL: `{jev_model()}`",
        f"- LLM_MODEL (openai arm): `{llm_model()}`",
        (
            f"- OpenAI cost model: `${OPENAI_INPUT_USD_PER_MTOK}/M` input + "
            f"`${OPENAI_OUTPUT_USD_PER_MTOK}/M` output (estimate from usage tokens)"
        ),
        (
            f"- Jev cost model: `${JEV_INPUT_USD_PER_MTOK}/M` input "
            "(estimate from usage tokens; use billed `cost_usd` when present)"
        ),
        f"- JEV_DECIDE_URL: `{jev_decide_url()}`",
        "",
        "## Summary",
        "",
        "| arm | n | correct | accuracy | mean latency (ms) | "
        "total cost (USD) | mean cost / call (USD) | notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for arm in arms:
        if arm.skipped:
            lines.append(
                f"| `{arm.name}` | — | — | — | — | — | — | skipped: {arm.skipped} |"
            )
            continue
        note = arm.cost_note or ""
        lines.append(
            f"| `{arm.name}` | {arm.n} | {arm.correct} | {arm.accuracy:.0%} | "
            f"{arm.mean_latency_ms:.0f} | {_format_usd(arm.total_cost_usd)} | "
            f"{_format_usd(arm.mean_cost_usd)} | {note} |"
        )

    lines.extend(["", "## Per-fixture labels", ""])
    arm_names = [a.name for a in arms]
    header = "| id | expected | " + " | ".join(arm_names) + " |"
    sep = "| --- | --- | " + " | ".join("---" for _ in arm_names) + " |"
    lines.extend([header, sep])

    ids: list[str] = []
    by_arm: dict[str, dict[str, CaseResult]] = {}
    for arm in arms:
        by_arm[arm.name] = {r.fixture_id: r for r in arm.results}
        for r in arm.results:
            if r.fixture_id not in ids:
                ids.append(r.fixture_id)
    if not ids and arms:
        try:
            ids = [str(f["id"]) for f in load_fixtures()]
        except Exception:  # noqa: BLE001
            ids = []

    expected_by_id: dict[str, str] = {}
    for arm in arms:
        for r in arm.results:
            expected_by_id[r.fixture_id] = r.expected
    if not expected_by_id:
        for fix in load_fixtures():
            expected_by_id[str(fix["id"])] = str(fix["label"])

    for fid in ids or list(expected_by_id):
        exp = expected_by_id.get(fid, "")
        cells = [f"`{fid}`", f"`{exp}`"]
        for name in arm_names:
            arm = next(a for a in arms if a.name == name)
            if arm.skipped:
                cells.append("—")
                continue
            r = by_arm[name].get(fid)
            if r is None:
                cells.append("—")
            elif r.correct:
                cells.append(f"`{r.predicted}` ok")
            else:
                pred = r.predicted if r.predicted is not None else "(none)"
                mark = f"`{pred}` miss"
                if r.error:
                    mark += " err"
                cells.append(mark)
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Per-fixture latency and cost", ""])
    # Columns: id | openai ms | openai $ | jev ms | jev $ | regex ms
    metric_arms = [a for a in arms if not a.skipped]
    metric_header_parts = ["id"]
    for a in metric_arms:
        metric_header_parts.append(f"{a.name} ms")
        metric_header_parts.append(f"{a.name} USD")
    lines.append("| " + " | ".join(metric_header_parts) + " |")
    lines.append(
        "| --- | " + " | ".join("---:" for _ in range(len(metric_header_parts) - 1)) + " |"
    )
    for fid in ids or list(expected_by_id):
        cells = [f"`{fid}`"]
        for arm in metric_arms:
            r = by_arm[arm.name].get(fid)
            if r is None:
                cells.extend(["—", "—"])
            else:
                cells.append(f"{r.latency_ms:.0f}")
                cells.append(_format_usd(r.cost_usd))
        lines.append("| " + " | ".join(cells) + " |")

    for arm in arms:
        lines.extend(_confusion_lines(arm))

    lines.extend(
        [
            "",
            "## Labels",
            "",
            ", ".join(f"`{lab}`" for lab in DIAGNOSE_INTENT_LABELS),
            "",
            "## Accept rule (ADR-0054)",
            "",
            "Accept Jev when its accuracy ≥ OpenAI on this set (tie → prefer Jev).",
            "At equal accuracy, lower latency / cost also favors Jev.",
            "Regex is a baseline only; it cannot emit `mid_cycle_stop` / "
            "`new_symptom` / `unclear`.",
            "",
        ]
    )

    openai = next((a for a in arms if a.name == "openai"), None)
    jev = next((a for a in arms if a.name == "jev"), None)
    if openai and jev and not openai.skipped and not jev.skipped:
        if jev.accuracy > openai.accuracy:
            lines.append(
                f"**Decision hint:** Jev {jev.accuracy:.0%} > OpenAI "
                f"{openai.accuracy:.0%} → accept ADR-0054 / prefer Jev."
            )
        elif jev.accuracy == openai.accuracy:
            lines.append(
                f"**Decision hint:** Tie at {jev.accuracy:.0%}. "
                f"Jev mean {jev.mean_latency_ms:.0f} ms / "
                f"${_format_usd(jev.mean_cost_usd)} vs OpenAI "
                f"{openai.mean_latency_ms:.0f} ms / "
                f"${_format_usd(openai.mean_cost_usd)} → prefer Jev (typed API)."
            )
        else:
            lines.append(
                f"**Decision hint:** Jev {jev.accuracy:.0%} < OpenAI "
                f"{openai.accuracy:.0%} → keep OpenAI classify; leave ADR Proposed "
                "or reject."
            )
    elif jev and jev.skipped:
        lines.append(
            f"**Decision hint:** Jev arm skipped ({jev.skipped}). "
            "Re-run with `JEV_API_KEY` before accepting ADR-0054."
        )
    lines.append("")
    return "\n".join(lines)


def write_scorecard(arms: list[ArmSummary], path: Path | None = None) -> Path:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "diagnose" / "results" / "scorecard.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scorecard_markdown(arms), encoding="utf-8")
    return path


__all__ = [
    "ArmSummary",
    "CaseResult",
    "OPENAI_INPUT_USD_PER_MTOK",
    "OPENAI_OUTPUT_USD_PER_MTOK",
    "load_fixtures",
    "regex_diagnose_label",
    "run_bakeoff",
    "scorecard_markdown",
    "write_scorecard",
]
