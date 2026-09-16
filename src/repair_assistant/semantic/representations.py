"""Compact retrieval representations for a semantic knowledge unit (ADR-0048).

A unit may be far larger than the embedder accepts, so what gets embedded is a
set of short representations that point back at it. These exist only for
discovery: generation always reads ``SemanticUnit.source_text``.

An over-budget representation is regenerated under a tighter instruction and, if
it still does not fit, handed to the reviewer marked ``over_limit``. It is never
truncated — silent truncation is the failure this design exists to avoid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from repair_assistant.prompts import prompt_digest, semantic_representations
from repair_assistant.semantic.env import representation_attempts, semantic_llm_model
from repair_assistant.semantic.schema import REPRESENTATIONS_RESPONSE_FORMAT
from repair_assistant.semantic.tokens import DEFAULT_TOKEN_BUDGET, count_tokens
from repair_assistant.semantic.units import SemanticUnit

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
#: Source text handed to the representation model. Generous, but bounded.
MAX_UNIT_CHARS_FOR_PROMPT = 24_000


class RepresentationClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class RepresentationError(RuntimeError):
    """The model returned something that is not a usable representation set."""


@dataclass
class Representation:
    """One embeddable surface pointing at a parent unit."""

    unit_key: str
    rep_kind: str
    text: str
    tokens: int = 0
    over_limit: bool = False
    origin: str = "llm"
    edited: bool = False

    @property
    def chunk_id(self) -> str:
        """Chunk id for the ``chunks`` row that carries this vector."""
        return f"u-{self.unit_key}-{self.rep_kind}"

    def to_json(self) -> dict[str, Any]:
        return {
            "unit_key": self.unit_key,
            "rep_kind": self.rep_kind,
            "text": self.text,
            "tokens": self.tokens,
            "over_limit": self.over_limit,
            "origin": self.origin,
            "edited": self.edited,
            "chunk_id": self.chunk_id,
        }


@dataclass
class RepresentationSet:
    unit_key: str
    representations: list[Representation] = field(default_factory=list)
    model: str = ""
    prompt_version: str = ""
    raw_output: str = ""
    attempts: int = 1
    #: Rows that actually needed a new vector. Unchanged text costs nothing,
    #: so this is what the review UI should report back to the reviewer.
    embedded: int = 0

    @property
    def over_limit(self) -> list[Representation]:
        return [r for r in self.representations if r.over_limit]


# --- builders ---------------------------------------------------------------
# Registered per kind so a fourth representation type is additive (decision 4).

RepresentationBuilder = Callable[[dict[str, Any]], str]


def _build_overview(payload: dict[str, Any]) -> str:
    return str(payload.get("overview") or "").strip()


def _build_facts(payload: dict[str, Any]) -> str:
    items = payload.get("facts")
    if not isinstance(items, list):
        return ""
    return "\n".join(str(i).strip() for i in items if str(i).strip())


def _build_questions(payload: dict[str, Any]) -> str:
    items = payload.get("questions")
    if not isinstance(items, list):
        return ""
    return "\n".join(str(i).strip() for i in items if str(i).strip())


BUILDERS: dict[str, RepresentationBuilder] = {
    "overview": _build_overview,
    "facts": _build_facts,
    "questions": _build_questions,
}


def register_builder(kind: str, builder: RepresentationBuilder) -> None:
    """Add a representation kind.

    Registering a builder is enough for parsing, persistence, and retrieval: the
    registry is what those read. A kind the *model* should fill in also needs a
    field on ``REPRESENTATIONS_SCHEMA``, which is strict by design.
    """
    BUILDERS[kind] = builder


# --- prompting --------------------------------------------------------------


def build_user_prompt(unit: SemanticUnit, *, tighten: bool = False) -> str:
    body = unit.source_text
    if len(body) > MAX_UNIT_CHARS_FOR_PROMPT:
        body = body[:MAX_UNIT_CHARS_FOR_PROMPT].rstrip() + "\n[unit continues]"
    lines = [
        f"Unit title: {unit.title or '(untitled)'}",
        f"Unit type: {unit.unit_type}",
    ]
    if unit.section_path:
        lines.append("Section: " + " > ".join(unit.section_path))
    if unit.page_label:
        lines.append(f"Source: {unit.page_label}")
    if tighten:
        lines.append(
            "A previous attempt was too long to embed. Keep the same coverage of "
            "codes, parts, and measurements, but cut every word that carries no "
            "search value. Shorter entries, fewer questions."
        )
    return "\n".join(lines) + "\n\nUnit content:\n" + body


def parse_representations(raw: str, unit: SemanticUnit) -> list[Representation]:
    """Build one representation per registered kind from the model's payload."""
    text = _FENCE.sub("", (raw or "").strip())
    if not text:
        raise RepresentationError("representation generation returned nothing")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepresentationError(f"representation output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RepresentationError("representation output is not a JSON object")

    out: list[Representation] = []
    for kind, builder in BUILDERS.items():
        body = builder(payload)
        if not body:
            continue
        out.append(
            Representation(
                unit_key=unit.unit_key,
                rep_kind=kind,
                text=body,
                tokens=count_tokens(body),
            )
        )
    if not out:
        raise RepresentationError(
            f"{unit.unit_key}: model produced no usable representations"
        )
    return out


def build_client(*, model: str | None = None) -> RepresentationClient:
    from repair_assistant.qa.generate import OpenAIClient
    from repair_assistant.semantic.env import (
        semantic_llm_base_url,
        semantic_openai_api_key,
    )

    return OpenAIClient(
        api_key=semantic_openai_api_key(),
        model=model or semantic_llm_model(),
        prompt_name="semantic_representations",
        response_format=REPRESENTATIONS_RESPONSE_FORMAT,
        base_url=semantic_llm_base_url(),
    )


def generate_representations(
    unit: SemanticUnit,
    *,
    llm: RepresentationClient,
    budget: int = DEFAULT_TOKEN_BUDGET,
    max_attempts: int | None = None,
    model: str = "",
) -> RepresentationSet:
    """Generate representations, retrying the ones that do not fit the embedder.

    Only the over-budget kinds are regenerated; a fitting overview is not thrown
    away because the facts list was long.
    """
    attempts = max_attempts if max_attempts is not None else representation_attempts()
    system = semantic_representations()
    accepted: dict[str, Representation] = {}
    raw_parts: list[str] = []
    used = 0

    for attempt in range(1, max(1, attempts) + 1):
        used = attempt
        raw = llm.complete(system, build_user_prompt(unit, tighten=attempt > 1))
        raw_parts.append(raw)
        for rep in parse_representations(raw, unit):
            existing = accepted.get(rep.rep_kind)
            if existing is not None and not existing.over_limit:
                continue
            rep.over_limit = rep.tokens > budget
            accepted[rep.rep_kind] = rep
        if all(not r.over_limit for r in accepted.values()):
            break

    ordered = [accepted[k] for k in BUILDERS if k in accepted]
    return RepresentationSet(
        unit_key=unit.unit_key,
        representations=ordered,
        model=model or semantic_llm_model(),
        prompt_version=prompt_digest("semantic_representations"),
        raw_output="\n".join(raw_parts),
        attempts=used,
    )


def edited_representation(
    unit_key: str,
    rep_kind: str,
    text: str,
    *,
    budget: int = DEFAULT_TOKEN_BUDGET,
) -> Representation:
    """A reviewer's own representation text, measured the same way."""
    body = (text or "").strip()
    tokens = count_tokens(body)
    return Representation(
        unit_key=unit_key,
        rep_kind=rep_kind,
        text=body,
        tokens=tokens,
        over_limit=tokens > budget,
        origin="human",
        edited=True,
    )
