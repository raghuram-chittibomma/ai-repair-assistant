"""Shared deterministic grading for Q&A eval scenarios."""

from __future__ import annotations

import re
from typing import Any

from repair_assistant.eval.groundedness import (
    groundedness_failure_detail,
    score_claims,
)
from repair_assistant.qa.structured import Claim, claims_from_dicts

# Machine-checkable keys that grade_answer enforces without --judge.
# Prose `expect` / `fails_if` are separate and need the LLM judge.
DETERMINISTIC_KEYS: tuple[str, ...] = (
    "must_cite",
    "must_not_cite",
    "must_not_cite_as_current",
    "expect_contains",
    "expect_contains_any",
    "expect_cites_any",
    "fails_if_contains",
    "expect_abstain",
    "expect_phase",
    "expect_ruled_out_any",
    "expect_hypotheses_any",
)


def has_deterministic_grading(scenario: dict[str, Any]) -> bool:
    """True if the scenario (after overlay merge) has ≥1 det grading rule."""
    if any(scenario.get(key) for key in DETERMINISTIC_KEYS):
        return True
    turn_grades = scenario.get("turn_grades") or {}
    for mini in turn_grades.values():
        if isinstance(mini, dict) and any(mini.get(key) for key in DETERMINISTIC_KEYS):
            return True
    return False


def grade_diagnose_turns(
    scenario: dict[str, Any],
    turns: list[Any],
) -> tuple[bool, str]:
    """Grade diagnose turns with optional per-turn ``turn_grades``.

    Each turn object needs ``.turn``, ``.assistant_message`` (or ``.answer``),
    ``.citations``, and ``.abstained``. When ``turn_grades`` is absent, falls
    back to top-level keys on ``expect_turn`` (default: last turn).
    """
    if not turns:
        return False, "no turns recorded"

    by_turn = {int(t.turn): t for t in turns}
    turn_grades = scenario.get("turn_grades")
    if turn_grades:
        failures: list[str] = []
        for raw_key in sorted(turn_grades.keys(), key=lambda k: int(k)):
            n = int(raw_key)
            mini = turn_grades[raw_key]
            if not isinstance(mini, dict):
                failures.append(f"turn {n}: invalid grade block")
                continue
            target = by_turn.get(n)
            if target is None:
                failures.append(f"turn {n}: missing")
                continue
            answer = getattr(target, "assistant_message", None)
            if answer is None:
                answer = getattr(target, "answer", "") or ""
            passed, detail = grade_answer(
                mini,
                answer=answer,
                citations=list(getattr(target, "citations", None) or []),
                abstained=bool(getattr(target, "abstained", False)),
                claims=list(getattr(target, "claims", None) or []),
                evidence_blocks=dict(getattr(target, "evidence_blocks", None) or {}),
                diagnostic=getattr(target, "diagnostic", None),
            )
            if not passed:
                failures.append(f"turn {n}: {detail}")
        if failures:
            return False, "; ".join(failures)
        return True, "ok"

    expect_turn = int(scenario.get("expect_turn") or turns[-1].turn)
    target = by_turn.get(expect_turn) or turns[-1]
    answer = getattr(target, "assistant_message", None)
    if answer is None:
        answer = getattr(target, "answer", "") or ""
    return grade_answer(
        scenario,
        answer=answer,
        citations=list(getattr(target, "citations", None) or []),
        abstained=bool(getattr(target, "abstained", False)),
        claims=list(getattr(target, "claims", None) or []),
        evidence_blocks=dict(getattr(target, "evidence_blocks", None) or {}),
        diagnostic=getattr(target, "diagnostic", None),
    )


_SUPERSESSION_ACK = re.compile(
    r"\b("
    r"superseded|no longer current|previous (?:revision|manual|edition|version)|"
    r"replaced by|older (?:manual|revision|edition)|not (?:the )?current"
    r")\b",
    re.I,
)

_PUB_NUM = re.compile(r"\b(W\d{8}|SYNTH-[A-Z0-9-]+)\b", re.I)
_PUB_GLUED_REV = re.compile(r"\b(W\d{8})([A-Z])\b")
_REV_LETTER = re.compile(r"\bRev\.?\s*([A-Z])\b", re.I)
_DOC_REV = re.compile(r"-rev([a-z])\b", re.I)


def parse_citation_ref(text: str) -> tuple[str | None, str | None]:
    """Return (publication_number, revision_letter) from a citation key or needle."""
    raw = (text or "").strip()
    if not raw:
        return None, None
    rev: str | None = None
    rev_m = _REV_LETTER.search(raw)
    if rev_m:
        rev = rev_m.group(1).upper()
    else:
        doc_rev = _DOC_REV.search(raw)
        if doc_rev:
            rev = doc_rev.group(1).upper()
        else:
            glued = _PUB_GLUED_REV.search(raw)
            if glued:
                return glued.group(1).upper(), glued.group(2).upper()
    pub_m = _PUB_NUM.search(raw)
    pub = pub_m.group(1).upper() if pub_m else None
    return pub, rev


def matches_citation(keys: list[str], needle: str) -> bool:
    """Match a required citation without treating every revision as interchangeable.

    A needle that names a revision (`W11169652 Rev B`, `W11169652B`,
    `service-manual-w11169652-revb`) matches only that revision. A bare
    publication number still matches any revision of that publication.
    """
    want_pub, want_rev = parse_citation_ref(needle)
    needle_l = needle.lower()
    for key in keys:
        have_pub, have_rev = parse_citation_ref(key)
        if want_pub and have_pub:
            if want_pub != have_pub:
                continue
            if want_rev is None or have_rev == want_rev:
                return True
            continue
        if want_pub and want_pub.lower() in key.lower():
            if want_rev is None:
                return True
            if have_rev == want_rev:
                return True
            continue
        if not want_pub:
            key_l = key.lower()
            if needle == key or key_l.startswith(needle_l) or needle_l == key_l:
                return True
    return False


def _as_claims(claims: list | None) -> list[Claim]:
    if not claims:
        return []
    out: list[Claim] = []
    for item in claims:
        if isinstance(item, Claim):
            out.append(item)
        elif isinstance(item, dict):
            out.extend(claims_from_dicts([item]))
    return out


def grade_answer(
    scenario: dict[str, Any],
    *,
    answer: str,
    citations: list[str],
    abstained: bool,
    claims: list | None = None,
    evidence_blocks: dict[int, str] | None = None,
    diagnostic: dict | None = None,
) -> tuple[bool, str]:
    """Return (passed, detail) for one scenario result."""
    failures: list[str] = []
    answer_text = answer.lower()
    board = diagnostic if isinstance(diagnostic, dict) else {}

    if scenario.get("expect_abstain") and not abstained:
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

    # Applies but must not be presented as the current authority unless the
    # answer acknowledges supersession / non-currency.
    for forbidden in scenario.get("must_not_cite_as_current") or []:
        if matches_citation(citations, forbidden) and not _SUPERSESSION_ACK.search(answer):
            failures.append(f"must_not_cite_as_current hit {forbidden!r}")

    if not abstained:
        for phrase in scenario.get("fails_if_contains") or []:
            if phrase.lower() in answer_text:
                failures.append(f"fails_if matched {phrase!r}")

    parsed_claims = _as_claims(claims)
    if parsed_claims and not abstained:
        report = score_claims(parsed_claims, evidence_blocks or {})
        hard = groundedness_failure_detail(report)
        if hard:
            failures.append(hard)

    want_phase = scenario.get("expect_phase")
    if want_phase and str(board.get("phase") or "") != str(want_phase):
        failures.append(
            f"expect_phase {want_phase!r}; got {board.get('phase')!r}"
        )
    ruled_hay = " ".join(str(x) for x in (board.get("ruled_out") or [])).lower()
    any_ruled = scenario.get("expect_ruled_out_any") or []
    if any_ruled and not any(phrase.lower() in ruled_hay for phrase in any_ruled):
        failures.append(
            f"expect_ruled_out_any missing one of {any_ruled}; got {board.get('ruled_out')}"
        )
    hypo_hay = " ".join(str(x) for x in (board.get("hypotheses") or [])).lower()
    any_hypo = scenario.get("expect_hypotheses_any") or []
    if any_hypo and not any(phrase.lower() in hypo_hay for phrase in any_hypo):
        failures.append(
            f"expect_hypotheses_any missing one of {any_hypo}; got {board.get('hypotheses')}"
        )

    if failures:
        return False, "; ".join(failures)
    return True, "ok"
