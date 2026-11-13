"""Natural-language assignments over a policy schema.

One translator is implemented. ``agree`` keeps a later second translator from
changing the solver or the release rule: copies must match, or the result is
ambiguous.
"""

from __future__ import annotations

from typing import Any, Protocol

from repair_assistant.reasoning.models import Formalization, Policy, Variable
from repair_assistant.reasoning.solver import coerce_value

_VALUE_PATTERNS = {"int": r"^-?[0-9]+$", "real": r"^-?[0-9]+(\.[0-9]+)?$"}


def _value_schema(var: Variable) -> dict[str, Any]:
    if var.type == "bool":
        return {"type": "string", "enum": ["true"] if var.role == "claim" else ["true", "false"]}
    if var.type == "enum":
        return {"type": "string", "enum": list(var.values)}
    return {"type": "string", "pattern": _VALUE_PATTERNS[var.type]}


def _assignment_schema(policy: Policy, role: str) -> dict[str, Any]:
    """One branch per variable, so a name can only carry a value of its own type."""
    branches = []
    for var in policy.variables:
        if var.role != role:
            continue
        properties: dict[str, Any] = {
            "name": {"type": "string", "enum": [var.name]},
            "value": _value_schema(var),
        }
        if role == "claim":
            properties["text"] = {"type": "string"}
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": list(properties),
            }
        )
    return {"type": "array", "items": {"anyOf": branches}}


def response_format(policy: Policy) -> dict[str, Any]:
    """Strict schema bound to this policy's names, roles, and value types."""
    names = [var.name for var in policy.variables]
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "policy_formalization",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "premises": _assignment_schema(policy, "fact"),
                    "claims": _assignment_schema(policy, "claim"),
                    "untranslated": {"type": "array", "items": {"type": "string"}},
                    "ambiguous": {
                        "type": "array",
                        "items": {"type": "string", "enum": names},
                    },
                },
                "required": ["premises", "claims", "untranslated", "ambiguous"],
            },
        },
    }


class Translator(Protocol):
    def translate(self, question: str, answer: str, policy: Policy) -> list[Formalization]:
        """Return one formalization per translator. Callers pass the list to ``agree``."""


def agree(formalizations: list[Formalization]) -> Formalization:
    if not formalizations:
        return Formalization(ambiguous=True, reason="no_formalization", confidence=0.0)
    if len(formalizations) == 1:
        return formalizations[0]
    head = formalizations[0]
    for other in formalizations[1:]:
        if other.premises != head.premises or other.claims != head.claims or other.ambiguous:
            return Formalization(ambiguous=True, reason="translators_disagreed", confidence=0.0)
    if head.ambiguous or head.confidence < 1.0:
        return head
    return Formalization(
        premises=dict(head.premises),
        claims=dict(head.claims),
        claim_text=dict(head.claim_text),
        untranslated=list(head.untranslated),
        confidence=1.0,
        ambiguous=False,
    )


def translation_prompt(policy: Policy) -> str:
    lines = [
        "Map the user message and the draft answer onto the policy variables.",
        "Premises use only fact variables: what the user stated.",
        "Claims use only claim variables: what the draft answer asserts.",
        "Omit a variable the turn does not assert.",
        "A claim records what the answer says. Never record that the answer leaves something out.",
        "When the turn concerns none of the variables, return empty premises, claims,"
        " and ambiguous.",
        "When the user raises a fact's topic without stating the fact, set that fact to its"
        " unknown value; do not omit it.",
        "Values are strings: true, false, an integer, or an enum name.",
        "List in ambiguous each variable the turn does address but in a way with two"
        " readings. Leave ambiguous empty otherwise.",
        "Put each answer sentence you cannot map into untranslated, verbatim with its [n] marker.",
        "",
        "Variables:",
    ]
    for var in policy.variables:
        values = f" values: {', '.join(var.values)}" if var.values else ""
        unknown = f"; unknown value: {var.unknown}" if var.unknown else ""
        requires = f"; only when {var.requires} is stated" if var.requires else ""
        lines.append(
            f"- {var.name} ({var.role}, {var.type}{values}{unknown}{requires}): "
            f"{var.description.strip()}"
        )
    lines.append("")
    lines.append("Rules:")
    for rule in policy.rules:
        lines.append(f"- {rule.id}: {rule.note or rule.expr}")
    return "\n".join(lines)


def parse_formalization(payload: Any, policy: Policy) -> Formalization:
    if not isinstance(payload, dict):
        return Formalization(ambiguous=True, reason="invalid_payload", confidence=0.0)
    untranslated = _strings(payload.get("untranslated"))
    premises, premise_error, _premise_text = _read_assignments(
        payload.get("premises"), policy, role="fact", with_text=False
    )
    flagged = payload.get("ambiguous")
    if isinstance(flagged, list):
        flagged = [name for name in _strings(flagged) if _in_scope(policy, name, premises)]
    if flagged is True or (isinstance(flagged, list) and flagged):
        names = flagged if isinstance(flagged, list) else []
        return Formalization(
            ambiguous=True,
            reason="model_ambiguous" + (f":{','.join(names)}" if names else ""),
            confidence=0.0,
            untranslated=untranslated,
        )
    claims, claim_error, claim_text = _read_assignments(
        payload.get("claims"),
        policy,
        role="claim",
        with_text=True,
        stated=premises,
        dropped=untranslated,
    )
    if premise_error or claim_error:
        return Formalization(
            ambiguous=True,
            reason=premise_error or claim_error,
            confidence=0.0,
            untranslated=untranslated,
        )
    return Formalization(
        premises=premises,
        claims=claims,
        claim_text=claim_text,
        untranslated=untranslated,
        confidence=1.0,
        ambiguous=False,
    )


class OpenAITranslator:
    """Single structured completion. Confidence is schema validity, not a vote."""

    def __init__(self, api_key: str, model: str, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def translate(self, question: str, answer: str, policy: Policy) -> list[Formalization]:
        from repair_assistant.qa.generate import OpenAIClient

        client = OpenAIClient(
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout,
            max_tokens=800,
            response_format=response_format(policy),
        )
        raw = client.complete(translation_prompt(policy), _user_text(question, answer))
        return [parse_formalization(_load_json(raw), policy)]


def translator_for_llm(llm: Any) -> OpenAITranslator | None:
    """Production OpenAI client only. Test doubles are not translators."""
    from repair_assistant.qa.generate import OpenAIClient

    if not isinstance(llm, OpenAIClient):
        return None
    key = (getattr(llm, "api_key", "") or "").strip()
    model = (getattr(llm, "model", "") or "").strip()
    if not key or not model:
        return None
    timeout = getattr(llm, "timeout", None)
    return OpenAITranslator(api_key=key, model=model, timeout=timeout)


def _user_text(question: str, answer: str) -> str:
    return f"Question:\n{question.strip()}\n\nDraft answer:\n{answer.strip()}"


def _load_json(raw: str) -> Any:
    import json

    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _in_scope(policy: Policy, name: str, premises: dict[str, Any]) -> bool:
    """A claim that requires a fact is out of scope until the user states that fact."""
    var = policy.variable(name)
    return var is None or not var.requires or var.requires in premises


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _read_assignments(
    value: Any,
    policy: Policy,
    *,
    role: str,
    with_text: bool,
    stated: dict[str, Any] | None = None,
    dropped: list[str] | None = None,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    if value is None:
        return {}, "", {}
    if not isinstance(value, list):
        return {}, "assignments must be a list", {}
    assigned: dict[str, Any] = {}
    texts: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            return {}, "assignment must be an object", {}
        name = str(item.get("name") or "").strip()
        raw_value = str(item.get("value") or "").strip()
        if not name and not raw_value:
            continue
        var = policy.variable(name)
        if var is None:
            return {}, f"unknown variable {name}", {}
        if var.role != role:
            return {}, f"{name} is a {var.role}, not a {role}", {}
        if not raw_value:
            continue
        try:
            coerced = coerce_value(var.type, var.values, raw_value)
        except (TypeError, ValueError) as exc:
            return {}, str(exc), {}
        omitted = role == "claim" and var.type == "bool" and coerced is False
        if omitted or (var.requires and var.requires not in (stated or {})):
            if dropped is not None:
                text = str(item.get("text") or "").strip()
                if text and text not in dropped:
                    dropped.append(text)
            continue
        if name in assigned and assigned[name] != coerced:
            return {}, f"conflicting values for {name}", {}
        assigned[name] = coerced
        if with_text:
            texts[name] = str(item.get("text") or "").strip()
    return assigned, "", texts
