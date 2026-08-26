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

from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.qa.generate import OpenAIClient

_SYSTEM = """You grade repair-assistant answers against scenario criteria.
Return ONLY a JSON object with keys:
  "passed": boolean
  "reason": short string (one sentence)
Rules:
- Prefer FAIL when the answer clearly violates fails_if.
- Prefer FAIL when expect describes required content that is missing or wrong.
- Prefer PASS when the answer substantially meets expect and does not violate fails_if.
- Do not invent corpus facts; judge only the given answer text and citations.
- Ignore citation formatting unless the criteria mention citations.
"""


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
        "Criteria:",
    ]
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
) -> JudgeVerdict:
    """Grade prose expect/fails_if. No-op PASS when there are no prose criteria."""
    if not needs_llm_judge(scenario):
        return JudgeVerdict(passed=True, reason="no prose criteria")
    client: JudgeClient = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
    raw = client.complete(
        _SYSTEM,
        build_judge_user_prompt(
            scenario,
            answer=answer,
            citations=citations,
            abstained=abstained,
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
) -> tuple[bool, str]:
    """Run deterministic grading, then optional LLM judge for prose criteria."""
    passed, detail = deterministic_grade(
        scenario,
        answer=answer,
        citations=citations,
        abstained=abstained,
    )
    if not passed or not use_judge or not needs_llm_judge(scenario):
        return passed, detail
    verdict = judge_answer(
        scenario,
        answer=answer,
        citations=citations,
        abstained=abstained,
        llm=llm,
    )
    if verdict.passed:
        return True, f"ok; judge: {verdict.reason}"
    return False, f"judge: {verdict.reason}"
