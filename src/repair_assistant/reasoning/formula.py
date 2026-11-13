"""Allowlisted policy formulas. The loader never evaluates formula text."""

from __future__ import annotations

from dataclasses import dataclass

_OPS = frozenset({"and", "or", "not", "=>", "=", ">", "<", ">=", "<="})


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Lit:
    value: bool | int | float


@dataclass(frozen=True)
class EnumLit:
    name: str


@dataclass(frozen=True)
class Call:
    op: str
    args: tuple[object, ...]


Expr = Var | Lit | EnumLit | Call


class FormulaError(ValueError):
    pass


def parse_formula(source: str) -> Expr:
    tokens = _tokenize(source)
    if not tokens:
        raise FormulaError("empty formula")
    expr, index = _parse(tokens, 0)
    if index != len(tokens):
        raise FormulaError(f"trailing input at {tokens[index]!r}")
    return expr


def node_count(expr: Expr) -> int:
    if isinstance(expr, Call):
        return 1 + sum(node_count(arg) for arg in expr.args if isinstance(arg, (Var, Lit, EnumLit, Call)))
    return 1


def _tokenize(source: str) -> list[str]:
    spaced = source.replace("(", " ( ").replace(")", " ) ")
    return [part for part in spaced.split() if part]


def _parse(tokens: list[str], index: int) -> tuple[Expr, int]:
    if index >= len(tokens):
        raise FormulaError("unexpected end of formula")
    token = tokens[index]
    if token != "(":
        return _atom(token), index + 1
    if index + 1 >= len(tokens):
        raise FormulaError("unclosed formula")
    op = tokens[index + 1]
    if op not in _OPS:
        raise FormulaError(f"operator {op!r} is not allowed")
    cursor = index + 2
    args: list[Expr] = []
    while cursor < len(tokens) and tokens[cursor] != ")":
        arg, cursor = _parse(tokens, cursor)
        args.append(arg)
    if cursor >= len(tokens) or tokens[cursor] != ")":
        raise FormulaError(f"unclosed {op} formula")
    _check_arity(op, len(args))
    return Call(op, tuple(args)), cursor + 1


def _check_arity(op: str, count: int) -> None:
    if op in {"not"} and count != 1:
        raise FormulaError("not takes one argument")
    if op in {"=>", "=", ">", "<", ">=", "<="} and count != 2:
        raise FormulaError(f"{op} takes two arguments")
    if op in {"and", "or"} and count < 2:
        raise FormulaError(f"{op} takes at least two arguments")


def _atom(token: str) -> Expr:
    lowered = token.lower()
    if lowered == "true":
        return Lit(True)
    if lowered == "false":
        return Lit(False)
    if token[:1] in "+-" and token[1:].isdigit() or token.isdigit():
        return Lit(int(token))
    if _is_real(token):
        return Lit(float(token))
    if not token.isidentifier():
        raise FormulaError(f"symbol {token!r} is not an identifier")
    return Var(token)


def _is_real(token: str) -> bool:
    if token.count(".") != 1:
        return False
    left, right = token.split(".")
    if left[:1] in "+-":
        left = left[1:]
    return bool(left) and left.isdigit() and bool(right) and right.isdigit()
