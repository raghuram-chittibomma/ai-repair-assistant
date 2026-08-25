"""Shared deterministic grading for Q&A eval scenarios."""

from __future__ import annotations

from typing import Any


def matches_citation(keys: list[str], needle: str) -> bool:
    needle_l = needle.lower()
    return any(
        needle == k
        or k.startswith(needle)
        or needle in k
        or needle_l in k.lower()
        for k in keys
    )


def grade_answer(
    scenario: dict[str, Any],
    *,
    answer: str,
    citations: list[str],
    abstained: bool,
) -> tuple[bool, str]:
    """Return (passed, detail) for one scenario result."""
    failures: list[str] = []
    answer_text = answer.lower()

    if scenario.get("expect_abstain"):
        if not abstained:
            failures.append("expected abstention")

    for needle in scenario.get("expect_contains") or []:
        if needle.lower() not in answer_text:
            failures.append(f"missing {needle!r}")

    any_of = scenario.get("expect_contains_any") or []
    if any_of and not any(phrase.lower() in answer_text for phrase in any_of):
        failures.append(f"expect_contains_any missing one of {any_of}")

    any_cite = scenario.get("expect_cites_any") or []
    if any_cite and not any(matches_citation(citations, req) for req in any_cite):
        failures.append(f"expect_cites_any missing one of {any_cite}; got {citations}")

    for required in scenario.get("must_cite") or []:
        if not matches_citation(citations, required):
            failures.append(f"must_cite missing {required!r}; got {citations}")

    for forbidden in scenario.get("must_not_cite") or []:
        if matches_citation(citations, forbidden):
            failures.append(f"must_not_cite hit {forbidden!r}")

    for phrase in scenario.get("fails_if_contains") or []:
        if phrase.lower() in answer_text:
            failures.append(f"fails_if matched {phrase!r}")

    if failures:
        return False, "; ".join(failures)
    return True, "ok"
