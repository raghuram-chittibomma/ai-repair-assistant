"""Load the published answer-invariants policy."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

from repair_assistant.reasoning.formula import (
    Call,
    EnumLit,
    Expr,
    FormulaError,
    Lit,
    Var,
    parse_formula,
)
from repair_assistant.reasoning.models import Policy, Rule, Variable

_TYPES = frozenset({"bool", "int", "real", "enum"})
_ROLES = frozenset({"fact", "claim"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PolicyError(ValueError):
    pass


def policy_config_path() -> Path:
    env = os.environ.get("REPAIR_REASONING_POLICY", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "reasoning" / "answer_invariants.yaml"
        if candidate.is_file():
            return candidate
    return here.parents[3] / "config" / "reasoning" / "answer_invariants.yaml"


def load_policy(path: Path | None = None) -> Policy:
    source = path or policy_config_path()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PolicyError(f"{source} must be a mapping")
    policy = _policy_from_mapping(raw)
    _typecheck_policy(policy)
    return policy


@lru_cache(maxsize=4)
def load_answer_invariants() -> Policy:
    return load_policy(policy_config_path())


def _policy_from_mapping(raw: dict) -> Policy:
    policy_id = str(raw.get("id") or "").strip()
    if not policy_id:
        raise PolicyError("policy id is required")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PolicyError("policy version must be a positive integer")
    variables = tuple(_variable(item) for item in _as_list(raw.get("variables"), "variables"))
    rules = tuple(_rule(item) for item in _as_list(raw.get("rules"), "rules"))
    if not variables or not rules:
        raise PolicyError("policy needs at least one variable and one rule")
    facts = {var.name for var in variables if var.role == "fact"}
    for var in variables:
        if var.requires and var.requires not in facts:
            raise PolicyError(f"{var.name}: requires must name a fact variable")
    names = [item.name for item in variables]
    if len(names) != len(set(names)):
        raise PolicyError("variable names must be unique")
    enum_values: list[str] = []
    for item in variables:
        enum_values.extend(item.values)
    if len(enum_values) != len(set(enum_values)):
        raise PolicyError("enum values share one namespace and must be unique")
    overlap = set(names) & set(enum_values)
    if overlap:
        raise PolicyError(f"names used as both a variable and an enum value: {sorted(overlap)}")
    rule_ids = [item.id for item in rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise PolicyError("rule ids must be unique")
    return Policy(id=policy_id, version=version, variables=variables, rules=rules)


def _as_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise PolicyError(f"{label} must be a list")
    return value


def _variable(item: object) -> Variable:
    if not isinstance(item, dict):
        raise PolicyError("each variable must be a mapping")
    name = str(item.get("name") or "").strip()
    kind = str(item.get("type") or "").strip()
    description = str(item.get("description") or "").strip()
    if not _IDENT.match(name):
        raise PolicyError(f"variable name {name!r} is not an identifier")
    if kind not in _TYPES:
        raise PolicyError(f"{name}: type must be bool, int, real, or enum")
    if not description:
        raise PolicyError(f"{name}: description is required")
    role = str(item.get("role") or "").strip()
    if role not in _ROLES:
        raise PolicyError(f"{name}: role must be fact or claim")
    values = item.get("values") or []
    unknown = str(item.get("unknown") or "").strip()
    if kind == "enum":
        if not isinstance(values, list) or len(values) < 2:
            raise PolicyError(f"{name}: an enum needs at least two values")
        cleaned = tuple(str(value).strip() for value in values)
        if any(not _IDENT.match(value) for value in cleaned):
            raise PolicyError(f"{name}: enum values must be identifiers")
        if unknown and unknown not in cleaned:
            raise PolicyError(f"{name}: unknown must be one of its values")
        if unknown and role != "fact":
            raise PolicyError(f"{name}: only a fact may declare an unknown value")
    else:
        if values:
            raise PolicyError(f"{name}: only enums declare values")
        if unknown:
            raise PolicyError(f"{name}: only enums declare an unknown value")
        cleaned = ()
    ask = " ".join(str(item.get("ask") or "").split())
    if ask and role != "fact":
        raise PolicyError(f"{name}: only a fact may declare an ask question")
    requires = str(item.get("requires") or "").strip()
    if requires and role != "claim":
        raise PolicyError(f"{name}: only a claim may declare requires")
    return Variable(
        name=name,
        type=kind,
        description=description,
        values=cleaned,
        role=role,
        unknown=unknown,
        ask=ask,
        requires=requires,
    )


def _rule(item: object) -> Rule:
    if not isinstance(item, dict):
        raise PolicyError("each rule must be a mapping")
    rule_id = str(item.get("id") or "").strip()
    expr = str(item.get("expr") or "").strip()
    note = str(item.get("note") or "").strip()
    if not rule_id:
        raise PolicyError("rule id is required")
    if not expr:
        raise PolicyError(f"{rule_id}: expr is required")
    try:
        parse_formula(expr)
    except FormulaError as exc:
        raise PolicyError(f"{rule_id}: {exc}") from exc
    return Rule(id=rule_id, expr=expr, note=note)


def _typecheck_policy(policy: Policy) -> None:
    for rule in policy.rules:
        expr = parse_formula(rule.expr)
        kind = _expr_type(expr, policy)
        if kind != "bool":
            raise PolicyError(f"{rule.id}: a rule must be a boolean formula")


def _expr_type(expr: Expr, policy: Policy) -> str:
    if isinstance(expr, Lit):
        if isinstance(expr.value, bool):
            return "bool"
        if isinstance(expr.value, int):
            return "int"
        return "real"
    if isinstance(expr, EnumLit):
        return policy.enum_owners[expr.name]
    if isinstance(expr, Var):
        if expr.name in policy.enum_owners and policy.variable(expr.name) is None:
            return policy.enum_owners[expr.name]
        var = policy.variable(expr.name)
        if var is None:
            raise PolicyError(f"unknown symbol {expr.name}")
        if var.type == "enum":
            return var.name
        return var.type
    if not isinstance(expr, Call):
        raise PolicyError(f"unknown expression {expr!r}")
    if expr.op == "not":
        _expect_bool(_expr_type(expr.args[0], policy), "not")
        return "bool"
    if expr.op in {"and", "or"}:
        for arg in expr.args:
            _expect_bool(_expr_type(arg, policy), expr.op)
        return "bool"
    if expr.op == "=>":
        _expect_bool(_expr_type(expr.args[0], policy), "=>")
        _expect_bool(_expr_type(expr.args[1], policy), "=>")
        return "bool"
    left = _resolve(expr.args[0], policy)
    right = _resolve(expr.args[1], policy)
    left_type = _expr_type(left, policy)
    right_type = _expr_type(right, policy)
    if expr.op == "=":
        if left_type != right_type:
            raise PolicyError(f"cannot compare {left_type} with {right_type}")
        return "bool"
    if left_type not in {"int", "real"} or right_type not in {"int", "real"}:
        raise PolicyError(f"{expr.op} requires numbers")
    if left_type != right_type:
        raise PolicyError(f"{expr.op} mixes {left_type} and {right_type}")
    return "bool"


def _resolve(expr: Expr, policy: Policy) -> Expr:
    if isinstance(expr, Var) and policy.variable(expr.name) is None and expr.name in policy.enum_owners:
        return EnumLit(expr.name)
    return expr


def _expect_bool(kind: str, op: str) -> None:
    if kind != "bool":
        raise PolicyError(f"{op} requires a boolean argument, got {kind}")
