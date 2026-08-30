"""Inspectable diagnostic board (ADR-0031 / review R31)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PHASES = frozenset(
    {
        "identify",
        "symptoms",
        "clarify",
        "causes",
        "next_step",
        "incorporate",
        "recommend",
        "escalate",
        "close",
    }
)

MAX_ITEMS = 12
MAX_ITEM_CHARS = 160


@dataclass
class Observation:
    text: str
    source: str = "user"
    turn: int = 0


@dataclass
class DiagnosticDelta:
    phase: str = ""
    hypotheses: list[str] = field(default_factory=list)
    ruled_out: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    next_check: str = ""


@dataclass
class DiagnosticBoard:
    step: int = 0
    phase: str = "symptoms"
    symptom_anchor: str = ""
    hypotheses: list[str] = field(default_factory=list)
    ruled_out: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    next_check: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "phase": self.phase,
            "symptom_anchor": self.symptom_anchor,
            "hypotheses": list(self.hypotheses),
            "ruled_out": list(self.ruled_out),
            "observations": [
                {"text": item.text, "source": item.source, "turn": item.turn}
                for item in self.observations
            ],
            "next_check": self.next_check,
        }


def _clip(text: str) -> str:
    return " ".join((text or "").split())[:MAX_ITEM_CHARS].strip()


def _norm(text: str) -> str:
    return _clip(text).lower()


def _dedupe_strings(existing: list[str], incoming: list[str]) -> list[str]:
    seen = {_norm(item) for item in existing if _norm(item)}
    out = [item for item in existing if _clip(item)]
    for raw in incoming:
        text = _clip(raw)
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[-MAX_ITEMS:]


def _append_observation(
    existing: list[Observation], item: Observation
) -> list[Observation]:
    text = _clip(item.text)
    if not text:
        return existing
    key = _norm(text)
    if any(_norm(obs.text) == key for obs in existing):
        return existing
    return [*existing, Observation(text=text, source=item.source, turn=item.turn)][
        -MAX_ITEMS:
    ]


def board_from_mapping(data: object) -> DiagnosticBoard:
    if not isinstance(data, dict):
        return DiagnosticBoard()
    observations: list[Observation] = []
    for row in data.get("observations") or []:
        if isinstance(row, dict):
            text = _clip(str(row.get("text") or ""))
            if text:
                observations.append(
                    Observation(
                        text=text,
                        source=str(row.get("source") or "user"),
                        turn=int(row.get("turn") or 0),
                    )
                )
        elif isinstance(row, str) and _clip(row):
            observations.append(Observation(text=_clip(row), source="assistant"))
    phase = str(data.get("phase") or "symptoms")
    if phase not in PHASES:
        phase = "symptoms"
    return DiagnosticBoard(
        step=int(data.get("step") or 0),
        phase=phase,
        symptom_anchor=_clip(str(data.get("symptom_anchor") or "")),
        hypotheses=[_clip(str(x)) for x in (data.get("hypotheses") or []) if _clip(str(x))],
        ruled_out=[_clip(str(x)) for x in (data.get("ruled_out") or []) if _clip(str(x))],
        observations=observations[-MAX_ITEMS:],
        next_check=_clip(str(data.get("next_check") or "")),
    )


def parse_delta(data: object) -> DiagnosticDelta | None:
    if not isinstance(data, dict):
        return None
    phase = str(data.get("phase") or "").strip()
    return DiagnosticDelta(
        phase=phase if phase in PHASES else "",
        hypotheses=[str(x) for x in (data.get("hypotheses") or []) if str(x).strip()],
        ruled_out=[str(x) for x in (data.get("ruled_out") or []) if str(x).strip()],
        observations=[
            str(x) for x in (data.get("observations") or []) if str(x).strip()
        ],
        next_check=str(data.get("next_check") or ""),
    )


def delta_from_raw(raw: str | None) -> DiagnosticDelta | None:
    if not raw:
        return None
    from repair_assistant.qa.structured import parse_model_output

    parsed = parse_model_output(raw)
    return parse_delta(parsed.diagnostic)


def merge_board(
    prior: DiagnosticBoard,
    *,
    step: int,
    symptom_anchor: str,
    user_message: str,
    delta: DiagnosticDelta | None = None,
) -> DiagnosticBoard:
    board = DiagnosticBoard(
        step=max(0, int(step)),
        phase=prior.phase or "symptoms",
        symptom_anchor=prior.symptom_anchor or _clip(symptom_anchor),
        hypotheses=list(prior.hypotheses),
        ruled_out=list(prior.ruled_out),
        observations=list(prior.observations),
        next_check=prior.next_check,
    )
    if user_message.strip():
        board.observations = _append_observation(
            board.observations,
            Observation(text=user_message, source="user", turn=board.step),
        )
    if delta is not None:
        if delta.phase in PHASES:
            board.phase = delta.phase
        board.ruled_out = _dedupe_strings(board.ruled_out, delta.ruled_out)
        ruled = {_norm(item) for item in board.ruled_out}
        if delta.hypotheses:
            board.hypotheses = []
            for item in delta.hypotheses:
                text = _clip(item)
                if text and _norm(text) not in ruled:
                    board.hypotheses = _dedupe_strings(board.hypotheses, [text])
        else:
            board.hypotheses = [
                item for item in board.hypotheses if _norm(item) not in ruled
            ]
        if _clip(delta.next_check):
            board.next_check = _clip(delta.next_check)
        for text in delta.observations:
            board.observations = _append_observation(
                board.observations,
                Observation(text=text, source="assistant", turn=board.step),
            )
    if not board.phase:
        board.phase = "symptoms" if board.step <= 1 else "next_step"
    return board


def merge_from_raw(
    prior_mapping: object,
    *,
    step: int,
    symptom_anchor: str,
    user_message: str,
    raw: str | None = None,
    phase_hint: str | None = None,
) -> DiagnosticBoard:
    delta = delta_from_raw(raw)
    if phase_hint and phase_hint in PHASES and (delta is None or not delta.phase):
        if delta is None:
            delta = DiagnosticDelta(phase=phase_hint)
        else:
            delta.phase = phase_hint
    return merge_board(
        board_from_mapping(prior_mapping),
        step=step,
        symptom_anchor=symptom_anchor,
        user_message=user_message,
        delta=delta,
    )


def format_board(board: DiagnosticBoard) -> str:
    lines = [
        "Session diagnostic board (authoritative — do not invent ruled-out checks):",
        f"step: {board.step}  phase: {board.phase}",
    ]
    if board.symptom_anchor:
        lines.append(f"symptom: {board.symptom_anchor}")
    if board.hypotheses:
        lines.append("open hypotheses: " + "; ".join(board.hypotheses))
    if board.ruled_out:
        lines.append("ruled out: " + "; ".join(board.ruled_out))
    else:
        lines.append("ruled out: (none yet)")
    if board.next_check:
        lines.append(f"next check: {board.next_check}")
    return "\n".join(lines)
