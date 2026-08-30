"""Structured claim→evidence binding (ADR-0028 / review R23)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from repair_assistant.qa.context import Citation, citations_from_answer

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CITE_REF = re.compile(r"\[(\d+)\]")

GROUNDED_ANSWER_SCHEMA: dict = {
    "name": "grounded_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "abstained": {"type": "boolean"},
            "abstain_reason": {"type": "string"},
            "answer": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "evidence_index": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}]
                        },
                    },
                    "required": ["text", "evidence_index"],
                },
            },
        },
        "required": ["abstained", "abstain_reason", "answer", "claims"],
    },
}

OPENAI_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": GROUNDED_ANSWER_SCHEMA,
}


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_index: int | None


@dataclass
class StructuredAnswer:
    abstained: bool = False
    abstain_reason: str = ""
    answer: str = ""
    claims: list[Claim] = field(default_factory=list)


@dataclass
class BoundGeneration:
    display: str
    abstained: bool
    abstain_reason: str
    claims: list[Claim]
    citations: list[Citation]


def _coerce_index(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        idx = int(value.strip())
        return idx if idx > 0 else None
    return None


def claims_from_prose(answer: str) -> list[Claim]:
    """Fallback: one claim per sentence that mentions [n]."""
    text = (answer or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE.split(text) if p.strip()]
    if not parts:
        parts = [text]
    claims: list[Claim] = []
    for part in parts:
        match = _CITE_REF.search(part)
        idx = int(match.group(1)) if match else None
        claims.append(Claim(text=part, evidence_index=idx))
    if not any(c.evidence_index for c in claims) and _CITE_REF.search(text):
        return [Claim(text=text, evidence_index=int(_CITE_REF.search(text).group(1)))]
    return claims


def _try_json(raw: str) -> dict | None:
    stripped = _FENCE.sub("", raw.strip()).strip()
    if not stripped.startswith("{"):
        return None
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _from_dict(data: dict) -> StructuredAnswer:
    claims: list[Claim] = []
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        claims.append(Claim(text=text, evidence_index=_coerce_index(item.get("evidence_index"))))
    answer = str(data.get("answer") or "")
    abstained = bool(data.get("abstained"))
    reason = str(data.get("abstain_reason") or "").strip()
    if not claims and answer and not abstained:
        claims = claims_from_prose(answer)
    return StructuredAnswer(
        abstained=abstained,
        abstain_reason=reason,
        answer=answer,
        claims=claims,
    )


def parse_model_output(raw: str) -> StructuredAnswer:
    """Accept JSON, ``ABSTAIN:`` prose, or cited prose (tests / fallback)."""
    text = (raw or "").strip()
    if not text:
        return StructuredAnswer(abstained=True, abstain_reason="empty model output")
    loaded = _try_json(text)
    if loaded is not None:
        return _from_dict(loaded)
    if text.upper().startswith("ABSTAIN:"):
        reason = text.split(":", 1)[-1].strip()
        return StructuredAnswer(abstained=True, abstain_reason=reason, answer=text)
    return StructuredAnswer(answer=text, claims=claims_from_prose(text))


def display_text(parsed: StructuredAnswer) -> str:
    if parsed.abstained:
        if (parsed.answer or "").upper().startswith("ABSTAIN:"):
            return parsed.answer
        reason = parsed.abstain_reason or parsed.answer or "insufficient evidence"
        return f"ABSTAIN: {reason}"
    if parsed.answer.strip():
        return parsed.answer
    if parsed.claims:
        lines = []
        for claim in parsed.claims:
            if claim.evidence_index:
                lines.append(f"{claim.text} [{claim.evidence_index}]")
            else:
                lines.append(claim.text)
        return "\n".join(lines)
    return ""


def citations_from_claims(
    claims: list[Claim],
    available: list[Citation],
) -> list[Citation]:
    by_index = {c.index: c for c in available}
    seen: set[int] = set()
    out: list[Citation] = []
    for claim in claims:
        idx = claim.evidence_index
        if idx is None or idx not in by_index or idx in seen:
            continue
        seen.add(idx)
        out.append(by_index[idx])
    return out


def bind_generation(raw: str, available: list[Citation]) -> BoundGeneration:
    parsed = parse_model_output(raw)
    display = display_text(parsed)
    if parsed.abstained:
        return BoundGeneration(
            display=display,
            abstained=True,
            abstain_reason=parsed.abstain_reason
            or display.split(":", 1)[-1].strip(),
            claims=list(parsed.claims),
            citations=[],
        )
    cited = citations_from_claims(parsed.claims, available)
    if not cited:
        cited = citations_from_answer(display, available)
    return BoundGeneration(
        display=display,
        abstained=False,
        abstain_reason="",
        claims=list(parsed.claims),
        citations=cited,
    )


def claims_as_dicts(claims: list[Claim]) -> list[dict]:
    return [{"text": c.text, "evidence_index": c.evidence_index} for c in claims]


def claims_from_dicts(rows: list[dict] | None) -> list[Claim]:
    out: list[Claim] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append(Claim(text=text, evidence_index=_coerce_index(item.get("evidence_index"))))
    return out
