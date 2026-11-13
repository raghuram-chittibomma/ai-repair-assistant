"""Shared records for policy entailment. Values stay JSON-safe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Variable:
    name: str
    type: str
    description: str
    values: tuple[str, ...] = ()
    #: ``fact`` is something the user states; ``claim`` is something the answer asserts.
    role: str = "fact"
    #: Enum value meaning the user did not say. Treated as missing, not as a fact.
    unknown: str = ""
    #: User-facing question when this fact is missing. The description is for the translator.
    ask: str = ""
    #: Fact a claim is about. Without that fact stated, the claim is not checked.
    requires: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    expr: str
    note: str = ""


@dataclass(frozen=True)
class Policy:
    id: str
    version: int
    variables: tuple[Variable, ...]
    rules: tuple[Rule, ...]

    def variable(self, name: str) -> Variable | None:
        for item in self.variables:
            if item.name == name:
                return item
        return None

    @property
    def enum_owners(self) -> dict[str, str]:
        """Enum value → the variable type name that owns it."""
        owners: dict[str, str] = {}
        for item in self.variables:
            for value in item.values:
                owners[value] = item.name
        return owners


@dataclass
class Formalization:
    premises: dict[str, Any] = field(default_factory=dict)
    claims: dict[str, Any] = field(default_factory=dict)
    claim_text: dict[str, str] = field(default_factory=dict)
    untranslated: list[str] = field(default_factory=list)
    confidence: float = 0.0
    ambiguous: bool = False
    reason: str = ""

    @property
    def pre_solve(self) -> str | None:
        """Outcome that is decided before Z3 runs."""
        if self.ambiguous or self.confidence < 1.0:
            return "translation_ambiguous"
        if not self.premises and not self.claims:
            return "no_translations"
        return None


@dataclass
class Finding:
    outcome: str
    rule_ids: list[str] = field(default_factory=list)
    premises: dict[str, Any] = field(default_factory=dict)
    claims: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] | None = None
    counterexample: dict[str, Any] | None = None
    claim_outcomes: list[dict[str, Any]] = field(default_factory=list)
    untranslated: list[str] = field(default_factory=list)
    confidence: float | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "rules": list(self.rule_ids),
            "premises": dict(self.premises),
            "claims": dict(self.claims),
        }
        if self.model is not None:
            payload["model"] = self.model
        if self.counterexample is not None:
            payload["counterexample"] = self.counterexample
        if self.claim_outcomes:
            payload["claim_outcomes"] = self.claim_outcomes
        if self.untranslated:
            payload["untranslated"] = self.untranslated
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass
class RewriteDraft:
    text: str
    claims: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    abstained: bool = False


@dataclass
class PolicyRelease:
    """What the answer path should do with a draft after the solver."""

    text: str
    mutates: bool
    reasoning: dict[str, Any]
    abstained: bool | None = None
    abstain_reason: str | None = None
    citations: list | None = None
    claims: list | None = None
