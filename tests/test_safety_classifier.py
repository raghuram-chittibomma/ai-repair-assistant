"""Regex ∪ LLM safety merge (ADR-0032 / R3). No live OpenAI."""

from __future__ import annotations

from repair_assistant.safety.classifier import (
    assess_layered,
    merge_assessments,
    parse_classifier_output,
)
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment
from repair_assistant.safety.policy import assess_request

_PARAPHRASE = "What's the trick techs use when they want it to agitate with the lid up?"


class FakeClassifier:
    def __init__(self, raw: str | None = None, *, boom: bool = False) -> None:
        self.raw = raw
        self.boom = boom
        self.calls = 0

    def classify(self, question: str, audience: Audience) -> SafetyAssessment | None:
        self.calls += 1
        if self.boom:
            raise RuntimeError("classifier down")
        if self.raw is None:
            return None
        return parse_classifier_output(self.raw, audience=audience)


def test_regex_misses_interlock_paraphrase() -> None:
    assert assess_request(_PARAPHRASE).action == SafetyAction.ALLOW


def test_union_raises_severity_on_paraphrase() -> None:
    clf = FakeClassifier(
        '{"action": "block", "rule_id": "bypass-interlock",'
        ' "reason": "Run with the lid open defeats the interlock."}'
    )
    layered = assess_layered(_PARAPHRASE, classifier=clf)
    assert clf.calls == 1
    assert layered.action == SafetyAction.BLOCK
    assert layered.rule_id.startswith("llm-")


def test_union_cannot_lower_regex_block() -> None:
    regex = assess_request("How do I bypass the door lock?")
    assert regex.action == SafetyAction.BLOCK
    merged = merge_assessments(
        regex,
        SafetyAssessment(
            action=SafetyAction.ALLOW,
            rule_id="allow",
            reason="",
            audience=Audience.OWNER,
        ),
    )
    assert merged.action == SafetyAction.BLOCK
    assert merged.rule_id == regex.rule_id


def test_classifier_failure_keeps_regex() -> None:
    layered = assess_layered(_PARAPHRASE, classifier=FakeClassifier(boom=True))
    assert layered.action == SafetyAction.ALLOW


def test_block_skips_classifier() -> None:
    clf = FakeClassifier(
        '{"action": "allow", "rule_id": "allow", "reason": ""}'
    )
    layered = assess_layered("How do I bypass the door lock?", classifier=clf)
    assert layered.action == SafetyAction.BLOCK
    assert clf.calls == 0


def test_parse_rejects_junk() -> None:
    assert parse_classifier_output("not json", audience=Audience.OWNER) is None
    assert parse_classifier_output('{"action": "maybe"}', audience=Audience.OWNER) is None
