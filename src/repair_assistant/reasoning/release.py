"""Release rule for a policy-covered claim."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

from repair_assistant.observability.langfuse_tracing import child_observation, update_span
from repair_assistant.reasoning.models import (
    Finding,
    Formalization,
    Policy,
    PolicyRelease,
    RewriteDraft,
)
from repair_assistant.reasoning.policy import load_answer_invariants
from repair_assistant.reasoning.solver import check_policy
from repair_assistant.reasoning.translator import Translator, agree

_log = logging.getLogger(__name__)
_CITE = re.compile(r"\[(\d+)\]")

Rewrite = Callable[[str], RewriteDraft | str]


def apply_policy_release(
    *,
    question: str,
    answer: str,
    translator: Translator | None,
    rewrite: Rewrite | None = None,
    policy: Policy | None = None,
    citations: list | None = None,
) -> PolicyRelease:
    """Decide whether a draft answer ships, is rewritten once, or becomes a question."""
    with child_observation(
        "reasoning",
        input={"question": question, "answer_preview": (answer or "")[:500]},
    ) as span:
        started = time.perf_counter()
        release = _release(
            question=question,
            answer=answer,
            translator=translator,
            rewrite=rewrite,
            policy=policy,
            citations=list(citations or []),
        )
        release.reasoning["duration_ms"] = int((time.perf_counter() - started) * 1000)
        update_span(span, output=release.reasoning)
        return release


def _release(
    *,
    question: str,
    answer: str,
    translator: Translator | None,
    rewrite: Rewrite | None,
    policy: Policy | None,
    citations: list,
) -> PolicyRelease:
    if translator is None:
        return _skipped(answer, "no_translator")
    published = policy or load_answer_invariants()
    try:
        formalizations = translator.translate(question, answer, published)
    except Exception as exc:  # noqa: BLE001 — a failed extra call must not replace the answer
        _log.warning("Policy translation failed; leaving the answer: %s", exc)
        return _skipped(answer, "translator_error")
    formal = agree(formalizations)
    hint = formal.pre_solve
    if hint == "no_translations":
        return PolicyRelease(
            text=answer,
            mutates=False,
            reasoning=_trace(hint, formal, None),
        )
    if hint == "translation_ambiguous":
        return _question(answer, _clarify(published, None, formal), _trace(hint, formal, None))
    finding = check_policy(published, formal.premises, formal.claims)
    finding.untranslated = list(formal.untranslated)
    finding.confidence = formal.confidence
    if finding.outcome == "no_translations":
        return PolicyRelease(text=answer, mutates=False, reasoning=finding.as_dict())
    if finding.outcome == "valid":
        return PolicyRelease(text=answer, mutates=False, reasoning=finding.as_dict())
    if finding.outcome in {"satisfiable", "translation_ambiguous"}:
        return _question(
            answer,
            _clarify(published, finding, formal),
            finding.as_dict(),
        )
    if finding.outcome == "invalid" and rewrite is not None:
        return _rewrite_once(
            question=question,
            translator=translator,
            rewrite=rewrite,
            policy=published,
            finding=finding,
            formal=formal,
            citations=citations,
        )
    return _withhold(finding, formal.untranslated, citations)


def _rewrite_once(
    *,
    question: str,
    translator: Translator,
    rewrite: Rewrite,
    policy: Policy,
    finding: Finding,
    formal: Formalization,
    citations: list,
) -> PolicyRelease:
    try:
        draft = _as_draft(rewrite(_addendum(finding)))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Policy rewrite failed: %s", exc)
        return _withhold(finding, formal.untranslated, citations)
    try:
        second = agree(translator.translate(question, draft.text, policy))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Policy recheck failed: %s", exc)
        return _withhold(finding, formal.untranslated, citations)
    if second.pre_solve is None:
        recheck = check_policy(policy, second.premises, second.claims)
        recheck.untranslated = list(second.untranslated)
        recheck.confidence = second.confidence
    else:
        recheck = Finding(outcome=second.pre_solve, reason=second.reason, untranslated=list(second.untranslated))
    if recheck.outcome == "valid" and not draft.abstained:
        payload = recheck.as_dict()
        payload["rewritten"] = True
        return PolicyRelease(
            text=draft.text,
            mutates=True,
            reasoning=payload,
            abstained=False,
            abstain_reason="",
            citations=list(draft.citations),
            claims=list(draft.claims),
        )
    spans = second.untranslated or formal.untranslated
    held = recheck if recheck.outcome in {"invalid", "impossible", "too_complex"} else finding
    return _withhold(held, spans, citations)


def _skipped(answer: str, reason: str) -> PolicyRelease:
    return PolicyRelease(
        text=answer,
        mutates=False,
        reasoning={"outcome": "skipped", "reason": reason},
    )


def _question(answer: str, text: str, reasoning: dict[str, Any]) -> PolicyRelease:
    del answer
    return PolicyRelease(
        text=text,
        mutates=True,
        reasoning=reasoning,
        abstained=False,
        abstain_reason="",
        citations=[],
        claims=[],
    )


def _withhold(finding: Finding, untranslated: list[str], citations: list) -> PolicyRelease:
    body = _withhold_text(finding)
    extra = _cited_untranslated(untranslated)
    if extra:
        return PolicyRelease(
            text=f"{body}\n\n{extra}",
            mutates=True,
            reasoning=finding.as_dict(),
            abstained=False,
            abstain_reason=body,
            citations=citations_named_in(citations, extra),
            claims=[],
        )
    return PolicyRelease(
        text=body,
        mutates=True,
        reasoning=finding.as_dict(),
        abstained=True,
        abstain_reason=body,
        citations=[],
        claims=[],
    )


def citations_named_in(citations: list, text: str) -> list:
    indexes = {int(match) for match in _CITE.findall(text or "")}
    if not indexes:
        return []
    return [item for item in citations if getattr(item, "index", None) in indexes]


def _cited_untranslated(spans: list[str]) -> str:
    kept = [span.strip() for span in spans if span and _CITE.search(span)]
    return "\n\n".join(kept)


def _withhold_text(finding: Finding) -> str:
    rules = ", ".join(finding.rule_ids) or "a policy rule"
    if finding.outcome == "impossible":
        return f"Those facts conflict with {rules}, so I can't choose a side."
    if finding.outcome == "too_complex":
        return "I can't check that statement against the rules, so I won't state it as fact."
    return f"I can't state that, because it conflicts with {rules}."


_UNMATCHED = (
    "I could not check that answer against the rules I apply. "
    "Please describe the symptom again in your own words."
)


def _clarify(policy: Policy, finding: Finding | None, formal: Formalization) -> str:
    if finding is None or finding.outcome == "translation_ambiguous":
        _, _, flagged = formal.reason.partition(":")
        return _ask(policy, flagged.split(",") if flagged else []) or _UNMATCHED
    unknown = [
        name
        for name, value in finding.premises.items()
        if (var := policy.variable(name)) is not None and var.unknown and str(value) == var.unknown
    ]
    true_model = finding.model or {}
    false_model = finding.counterexample or {}
    diffs = [key for key in true_model if true_model.get(key) != false_model.get(key)]
    return _ask(policy, unknown + diffs) or "I need one more fact before I can confirm that."


def _ask(policy: Policy, names: list[str]) -> str:
    """The first named fact that has a user-facing question."""
    for name in names:
        var = policy.variable(name.strip())
        if var is not None and var.role == "fact" and var.ask:
            return f"I need one more fact before I can confirm that. {var.ask}"
    return ""


def _addendum(finding: Finding) -> str:
    rules = ", ".join(finding.rule_ids) or "a policy rule"
    return (
        "The previous answer conflicts with policy rule "
        f"{rules}. Claims: {finding.claims}. "
        f"A consistent assignment is {finding.counterexample}. "
        "Rewrite the answer so it does not state the contradicted claim. "
        "Do not add a procedure the evidence does not support. "
        "If you cannot correct it from the evidence, abstain."
    )


def _trace(outcome: str, formal: Formalization, finding: Finding | None) -> dict[str, Any]:
    if finding is not None:
        return finding.as_dict()
    payload: dict[str, Any] = {
        "outcome": outcome,
        "confidence": formal.confidence,
        "premises": dict(formal.premises),
        "claims": dict(formal.claims),
    }
    if formal.untranslated:
        payload["untranslated"] = list(formal.untranslated)
    if formal.reason:
        payload["reason"] = formal.reason
    return payload


def _as_draft(value: RewriteDraft | str) -> RewriteDraft:
    if isinstance(value, RewriteDraft):
        return value
    return RewriteDraft(text=str(value))
