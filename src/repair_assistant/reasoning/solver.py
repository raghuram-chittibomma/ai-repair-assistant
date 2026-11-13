"""Z3 check of a published policy against premises and claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import z3

from repair_assistant.reasoning.formula import (
    Call,
    EnumLit,
    Expr,
    Lit,
    Var,
    node_count,
    parse_formula,
)
from repair_assistant.reasoning.models import Finding, Policy
from repair_assistant.reasoning.policy import PolicyError, _resolve

TIMEOUT_MS = 2000
MAX_RULES = 64
MAX_NODES = 128

_WORST = ("too_complex", "impossible", "invalid", "satisfiable", "valid")


EnumSorts = dict[str, tuple[z3.SortRef, list[z3.ExprRef]]]


def enum_sorts(ctx: z3.Context, policy: Policy) -> EnumSorts:
    """Declare each enum sort once per context so compiled copies can share it."""
    return {
        var.name: z3.EnumSort(var.name, list(var.values), ctx=ctx)
        for var in policy.variables
        if var.type == "enum"
    }


class Compiled:
    """Rules as Z3 terms. ``claim_suffix`` renames claim variables for a second copy."""

    def __init__(
        self,
        ctx: z3.Context,
        policy: Policy,
        *,
        sorts: EnumSorts | None = None,
        claim_suffix: str = "",
    ) -> None:
        self.ctx = ctx
        self.policy = policy
        self.vars: dict[str, z3.ExprRef] = {}
        self.enums: dict[str, z3.ExprRef] = {}
        sorts = sorts if sorts is not None else enum_sorts(ctx, policy)
        for var in policy.variables:
            symbol = f"{var.name}{claim_suffix}" if var.role == "claim" else var.name
            if var.type == "bool":
                self.vars[var.name] = z3.Bool(symbol, ctx=ctx)
            elif var.type == "int":
                self.vars[var.name] = z3.Int(symbol, ctx=ctx)
            elif var.type == "real":
                self.vars[var.name] = z3.Real(symbol, ctx=ctx)
            else:
                sort, constructors = sorts[var.name]
                self.vars[var.name] = z3.Const(symbol, sort)
                for value, constructor in zip(var.values, constructors, strict=True):
                    self.enums[value] = constructor
        self.rules: list[tuple[str, z3.BoolRef]] = []
        for rule in policy.rules:
            expr = self.compile(parse_formula(rule.expr))
            if not z3.is_bool(expr):
                raise PolicyError(f"{rule.id}: a rule must be boolean")
            self.rules.append((rule.id, expr))

    def known_facts(self) -> list[z3.BoolRef]:
        """Exclude each fact's unknown value, so a fact means the user said it."""
        out: list[z3.BoolRef] = []
        for var in self.policy.variables:
            if var.role == "fact" and var.unknown:
                out.append(self.vars[var.name] != self.enums[var.unknown])
        return out

    def compile(self, expr: Expr) -> z3.ExprRef:
        resolved = _resolve(expr, self.policy)
        if isinstance(resolved, Call):
            return self._call(resolved)
        if isinstance(resolved, Var):
            return self.vars[resolved.name]
        if isinstance(resolved, EnumLit):
            return self.enums[resolved.name]
        if isinstance(resolved, Lit):
            if isinstance(resolved.value, bool):
                return z3.BoolVal(resolved.value, ctx=self.ctx)
            if isinstance(resolved.value, int):
                return z3.IntVal(resolved.value, ctx=self.ctx)
            return z3.RealVal(str(resolved.value), ctx=self.ctx)
        raise PolicyError(f"cannot compile {expr!r}")

    def _call(self, expr: Call) -> z3.ExprRef:
        args = [self.compile(arg) for arg in expr.args if isinstance(arg, (Var, Lit, EnumLit, Call))]
        if expr.op == "not":
            return z3.Not(args[0])
        if expr.op == "and":
            return z3.And(*args)
        if expr.op == "or":
            return z3.Or(*args)
        if expr.op == "=>":
            return z3.Implies(args[0], args[1])
        if expr.op == "=":
            return args[0] == args[1]
        if expr.op == ">":
            return args[0] > args[1]
        if expr.op == "<":
            return args[0] < args[1]
        if expr.op == ">=":
            return args[0] >= args[1]
        if expr.op == "<=":
            return args[0] <= args[1]
        raise PolicyError(f"operator {expr.op!r} is not allowed")

    def assignment(self, name: str, value: Any) -> z3.BoolRef:
        var = self.policy.variable(name)
        if var is None:
            raise PolicyError(f"unknown variable {name}")
        coerced = coerce_value(var.type, var.values, value)
        if var.type == "bool":
            literal: z3.ExprRef = z3.BoolVal(bool(coerced), ctx=self.ctx)
        elif var.type == "int":
            literal = z3.IntVal(int(coerced), ctx=self.ctx)
        elif var.type == "real":
            literal = z3.RealVal(str(coerced), ctx=self.ctx)
        else:
            literal = self.enums[str(coerced)]
        expr = self.vars[name] == literal
        if not z3.is_bool(expr):
            raise PolicyError(f"{name}: assignment is not boolean")
        return expr

    def read_model(self, model: z3.ModelRef) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for var in self.policy.variables:
            value = model.eval(self.vars[var.name], model_completion=True)
            out[var.name] = python_value(var.type, value)
        return out


@dataclass
class _Probe:
    status: str
    model: dict[str, Any] | None = None


def check_policy(
    policy: Policy,
    premises: dict[str, Any],
    claims: dict[str, Any],
) -> Finding:
    """Prove each claim from the rules and premises."""
    if len(policy.rules) > MAX_RULES:
        return Finding(outcome="too_complex", premises=dict(premises), claims=dict(claims), reason="rule_cap")
    nodes = 0
    for rule in policy.rules:
        nodes += node_count(parse_formula(rule.expr))
    if nodes > MAX_NODES:
        return Finding(outcome="too_complex", premises=dict(premises), claims=dict(claims), reason="size_cap")
    if not claims:
        return Finding(outcome="no_translations", premises=dict(premises), claims={})

    compiled = Compiled(z3.Context(), policy)
    try:
        premise_exprs = [(name, compiled.assignment(name, value)) for name, value in premises.items()]
        claim_exprs = [(name, compiled.assignment(name, value)) for name, value in claims.items()]
    except (PolicyError, TypeError, ValueError) as exc:
        return Finding(
            outcome="translation_ambiguous",
            premises=dict(premises),
            claims=dict(claims),
            reason=str(exc),
            confidence=0.0,
        )

    background = [expr for _, expr in compiled.rules] + [expr for _, expr in premise_exprs]
    base = _probe(compiled, background)
    if base.status == "unknown":
        return Finding(outcome="too_complex", premises=dict(premises), claims=dict(claims), reason="timeout")
    if base.status == "unsat":
        return Finding(
            outcome="impossible",
            rule_ids=_necessary_rules(compiled, premise_exprs, extra=[]),
            premises=dict(premises),
            claims=dict(claims),
        )

    parts: list[Finding] = []
    for name, expr in claim_exprs:
        parts.append(_one_claim(compiled, premise_exprs, name, expr, premises, claims))
    return _aggregate(parts, premises, claims)


def undecided_claims(policy: Policy) -> dict[str, dict[str, Any]]:
    """Claim variables the rules leave open even when every user fact is known.

    Two copies share the facts and duplicate the claims. If both copies satisfy
    the rules with the claim true in one and false in the other, the facts do
    not decide it, and a correct answer would come back ``satisfiable``. The
    value is one fact assignment that shows the gap.
    """
    ctx = z3.Context()
    sorts = enum_sorts(ctx, policy)
    left = Compiled(ctx, policy, sorts=sorts, claim_suffix="__a")
    right = Compiled(ctx, policy, sorts=sorts, claim_suffix="__b")
    shared = [expr for _, expr in left.rules] + [expr for _, expr in right.rules]
    shared += left.known_facts()
    gaps: dict[str, dict[str, Any]] = {}
    for var in policy.variables:
        if var.role != "claim":
            continue
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", TIMEOUT_MS)
        solver.add(*shared)
        solver.add(left.vars[var.name] != right.vars[var.name])
        result = solver.check()
        if result == z3.unsat:
            continue
        if result == z3.sat:
            model = solver.model()
            gaps[var.name] = {
                fact.name: python_value(
                    fact.type, model.eval(left.vars[fact.name], model_completion=True)
                )
                for fact in policy.variables
                if fact.role == "fact"
            }
        else:
            gaps[var.name] = {"reason": "timeout"}
    return gaps


def coerce_value(kind: str, values: tuple[str, ...], value: Any) -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise TypeError(f"expected a boolean, got {value!r}")
    if kind == "int":
        if isinstance(value, (bool, float)):
            raise TypeError(f"expected an integer, got {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        raise TypeError(f"expected an integer, got {value!r}")
    if kind == "real":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise TypeError(f"expected a number, got {value!r}")
        return float(value)
    if not isinstance(value, str):
        raise TypeError(f"expected an enum value, got {value!r}")
    token = value.strip()
    for allowed in values:
        if allowed.lower() == token.lower():
            return allowed
    raise TypeError(f"{token!r} is not one of {', '.join(values)}")


def python_value(kind: str, value: z3.ExprRef) -> Any:
    if kind == "bool":
        if z3.is_true(value):
            return True
        if z3.is_false(value):
            return False
        raise PolicyError("boolean model value was not concrete")
    if kind == "int":
        return int(value.as_long())
    if kind == "real":
        text = value.as_decimal(6)
        return float(text.rstrip("?"))
    return str(value)


def _probe(compiled: Compiled, exprs: list[z3.BoolRef]) -> _Probe:
    solver = z3.Solver(ctx=compiled.ctx)
    solver.set("timeout", TIMEOUT_MS)
    for expr in exprs:
        solver.add(expr)
    result = solver.check()
    if result == z3.sat:
        return _Probe("sat", compiled.read_model(solver.model()))
    if result == z3.unsat:
        return _Probe("unsat")
    return _Probe("unknown")


def _necessary_rules(
    compiled: Compiled,
    premises: list[tuple[str, z3.BoolRef]],
    extra: list[z3.BoolRef],
) -> list[str]:
    """Rules whose removal makes an unsatisfiable problem satisfiable."""
    needed: list[str] = []
    premise_exprs = [expr for _, expr in premises]
    for rule_id, _expr in compiled.rules:
        others = [item for name, item in compiled.rules if name != rule_id]
        probe = _probe(compiled, others + premise_exprs + extra)
        if probe.status != "unsat":
            needed.append(rule_id)
    return needed


def _one_claim(
    compiled: Compiled,
    premises: list[tuple[str, z3.BoolRef]],
    name: str,
    expr: z3.BoolRef,
    premise_values: dict[str, Any],
    claim_values: dict[str, Any],
) -> Finding:
    background = [item for _, item in compiled.rules] + [item for _, item in premises]
    holds = _probe(compiled, background + [expr])
    fails = _probe(compiled, background + [z3.Not(expr)])
    if holds.status == "unknown" or fails.status == "unknown":
        return Finding(outcome="too_complex", reason="timeout", claims={name: claim_values[name]})
    if holds.status == "unsat" and fails.status == "unsat":
        return Finding(outcome="impossible", claims={name: claim_values[name]})
    if fails.status == "unsat" and holds.status == "sat":
        return Finding(
            outcome="valid",
            rule_ids=_necessary_rules(compiled, premises, extra=[z3.Not(expr)]),
            model=holds.model,
            premises=dict(premise_values),
            claims={name: claim_values[name]},
        )
    if holds.status == "unsat" and fails.status == "sat":
        return Finding(
            outcome="invalid",
            rule_ids=_necessary_rules(compiled, premises, extra=[expr]),
            counterexample=fails.model,
            premises=dict(premise_values),
            claims={name: claim_values[name]},
        )
    return Finding(
        outcome="satisfiable",
        model=holds.model,
        counterexample=fails.model,
        premises=dict(premise_values),
        claims={name: claim_values[name]},
    )


def _aggregate(parts: list[Finding], premises: dict[str, Any], claims: dict[str, Any]) -> Finding:
    rank = {name: index for index, name in enumerate(_WORST)}
    worst = min(parts, key=lambda item: rank[item.outcome])
    same = [item for item in parts if item.outcome == worst.outcome]
    rules: list[str] = []
    for item in same:
        for rule_id in item.rule_ids:
            if rule_id not in rules:
                rules.append(rule_id)
    outcomes = [{"name": next(iter(item.claims)), "outcome": item.outcome} for item in parts if item.claims]
    model = next((item.model for item in same if item.model is not None), None)
    counter = next((item.counterexample for item in same if item.counterexample is not None), None)
    return Finding(
        outcome=worst.outcome,
        rule_ids=rules,
        premises=dict(premises),
        claims=dict(claims),
        model=model,
        counterexample=counter,
        claim_outcomes=outcomes,
        reason=worst.reason,
    )
