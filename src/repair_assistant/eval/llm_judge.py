"""Opt-in LLM-as-judge for prose ``expect`` / ``fails_if`` scenario fields.

Deterministic grading (``expect_contains``, ``must_cite``, …) remains the
default gate. When enabled, this module only evaluates free-text criteria that
substring rules cannot check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from repair_assistant.prompts import judge_system
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.qa.generate import OpenAIClient


class JudgeClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class JudgeVerdict:
    passed: bool
    reason: str
    raw: str = ""


def prose_criteria(scenario: dict[str, Any]) -> dict[str, str]:
    """Return non-empty prose fields the judge should evaluate."""
    out: dict[str, str] = {}
    for key in ("expect", "fails_if"):
        value = scenario.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def needs_llm_judge(scenario: dict[str, Any]) -> bool:
    return bool(prose_criteria(scenario))


def _parse_verdict(text: str) -> JudgeVerdict:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return JudgeVerdict(
            passed=False,
            reason=f"judge returned non-JSON: {text[:200]}",
            raw=text,
        )
    passed = bool(data.get("passed"))
    reason = str(data.get("reason") or ("ok" if passed else "failed")).strip()
    return JudgeVerdict(passed=passed, reason=reason, raw=text)


def build_judge_user_prompt(
    scenario: dict[str, Any],
    *,
    answer: str,
    citations: list[str],
    abstained: bool,
    evidence_text: str = "",
) -> str:
    criteria = prose_criteria(scenario)
    lines = [
        f"Scenario id: {scenario.get('id', '')}",
        f"Question: {scenario.get('question', '')}",
        f"Abstained: {abstained}",
        f"Citations: {', '.join(citations) or '(none)'}",
        "",
        "Answer:",
        answer or "(empty)",
        "",
    ]
    if evidence_text.strip():
        lines.extend(["Evidence:", evidence_text.strip(), ""])
    lines.append("Criteria:")
    if "expect" in criteria:
        lines.append(f"- expect: {criteria['expect']}")
    if "fails_if" in criteria:
        lines.append(f"- fails_if: {criteria['fails_if']}")
    lines.append("")
    lines.append('Respond with JSON: {"passed": true|false, "reason": "..."}')
    return "\n".join(lines)


def judge_answer(
    scenario: dict[str, Any],
    *,
    answer: str,
    citations: list[str],
    abstained: bool,
    llm: JudgeClient | None = None,
    evidence_text: str = "",
) -> JudgeVerdict:
    """Grade prose expect/fails_if. No-op PASS when there are no prose criteria."""
    if not needs_llm_judge(scenario):
        return JudgeVerdict(passed=True, reason="no prose criteria")
    client: JudgeClient = llm or OpenAIClient(
        api_key=openai_api_key(), model=llm_model(), prompt_name="judge_system"
    )
    raw = client.complete(
        judge_system(),
        build_judge_user_prompt(
            scenario,
            answer=answer,
            citations=citations,
            abstained=abstained,
            evidence_text=evidence_text,
        ),
    )
    return _parse_verdict(raw)


def grade_with_optional_judge(
    scenario: dict[str, Any],
    *,
    answer: str,
    citations: list[str],
    abstained: bool,
    use_judge: bool,
    llm: JudgeClient | None = None,
    deterministic_grade: Callable[..., tuple[bool, str]],
    evidence_text: str = "",
    claims: list | None = None,
    evidence_blocks: dict[int, str] | None = None,
) -> tuple[bool, str]:
    """Run deterministic grading, then optional LLM judge for prose criteria."""
    extra: dict[str, Any] = {}
    if claims is not None:
        extra["claims"] = claims
    if evidence_blocks is not None:
        extra["evidence_blocks"] = evidence_blocks
    passed, detail = deterministic_grade(
        scenario,
        answer=answer,
        citations=citations,
        abstained=abstained,
        **extra,
    )
    if not passed or not use_judge or not needs_llm_judge(scenario):
        return passed, detail
    verdict = judge_answer(
        scenario,
        answer=answer,
        citations=citations,
        abstained=abstained,
        llm=llm,
        evidence_text=evidence_text,
    )
    if verdict.passed:
        return True, f"ok; judge: {verdict.reason}"
    return False, f"judge: {verdict.reason}"
