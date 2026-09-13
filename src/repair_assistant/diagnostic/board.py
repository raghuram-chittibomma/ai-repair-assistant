"""Inspectable diagnostic board (ADR-0031 / review R31)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from repair_assistant.diagnostic.intent import procedure_needles
from repair_assistant.qa.acks import is_progress_followup

_NUMBERED_CHECK = re.compile(r"^\s*\d+\.\s+(.+)$")

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


_INLINE_NUMBERED = re.compile(r"(?:^|[\s*])(\d+)\.\s+")


def _clean_check(raw: str) -> str:
    item = re.sub(r"\s*\[\d+\]\s*$", "", _clip(raw))
    item = re.sub(r"\*+", "", item)
    return item.strip(" :.-")


def checks_from_assistant(text: str) -> list[str]:
    """Numbered checklist items from the previous assistant turn.

    Accepts one item per line or an inline ``1. … 2. …`` list (common when the
    model puts the whole category in one paragraph).
    """
    items: list[str] = []
    for line in (text or "").splitlines():
        match = _NUMBERED_CHECK.match(line)
        if not match:
            continue
        item = _clean_check(match.group(1))
        if item:
            items.append(item)
    if items:
        return items
    matches = list(_INLINE_NUMBERED.finditer(text or ""))
    if len(matches) < 2:
        return []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text or "")
        item = _clean_check((text or "")[start:end])
        if item:
            items.append(item)
    return items


def _procedure_keys(text: str) -> set[str]:
    return {needle.lower() for needle in procedure_needles(text)}


def _check_is_ruled_out(check: str, ruled_out: list[str]) -> bool:
    """Exact board item, or the same See TEST #N already confirmed."""
    if not _clip(check):
        return False
    if _norm(check) in {_norm(item) for item in ruled_out}:
        return True
    keys = _procedure_keys(check)
    if not keys:
        return False
    return any(
        keys & _procedure_keys(item) or _norm(item) in keys for item in ruled_out
    )


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


_PROGRESS_LABELS = frozenset({"ack", "still_unresolved"})


def is_board_progress(*, user_message: str, intent_label: str | None = None) -> bool:
    """Classify ack/unresolved, or the acks.py fallback."""
    if (intent_label or "") in _PROGRESS_LABELS:
        return True
    return is_progress_followup(user_message)


def should_close_exhausted_pointer(
    board: DiagnosticBoard, *, evidence_text: str
) -> bool:
    """True when every See TEST #N in the pack is already on the board."""
    tests = set(procedure_needles(evidence_text))
    if not tests:
        return False
    ruled: set[str] = set()
    for item in board.ruled_out:
        ruled.update(procedure_needles(item))
    return tests <= ruled


def exhausted_path_close_message(board: DiagnosticBoard) -> str:
    cleared = "; ".join(board.ruled_out[:6]) if board.ruled_out else "the checks already offered"
    return (
        f"The on-page path is complete ({cleared}) [1]. This evidence only "
        f"names a See TEST procedure without its steps, and that pointer was "
        f"already offered. There are no further grounded steps on this path."
    )


def merge_board(
    prior: DiagnosticBoard,
    *,
    step: int,
    symptom_anchor: str,
    user_message: str,
    delta: DiagnosticDelta | None = None,
    prior_assistant: str = "",
    intent_label: str | None = None,
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
    if is_board_progress(user_message=user_message, intent_label=intent_label):
        confirmed: list[str] = []
        if prior.next_check:
            confirmed.append(prior.next_check)
            confirmed.extend(procedure_needles(prior.next_check))
        confirmed.extend(checks_from_assistant(prior_assistant))
        confirmed.extend(procedure_needles(prior_assistant))
        if confirmed:
            # Model often forgets diagnostic.ruled_out on "that looks good" turns.
            board.ruled_out = _dedupe_strings(board.ruled_out, confirmed)
            ruled = {_norm(item) for item in board.ruled_out}
            board.hypotheses = [
                item for item in board.hypotheses if _norm(item) not in ruled
            ]
            if _check_is_ruled_out(board.next_check, board.ruled_out):
                board.next_check = ""
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
    prior_assistant: str = "",
    intent_label: str | None = None,
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
        prior_assistant=prior_assistant,
        intent_label=intent_label,
    )


_NEEDLE_ONLY = re.compile(r"^(?:see\s+)?test\s*#\s*(\d+)$", re.I)


def display_check_label(text: str) -> str:
    """User-facing check text — needle-only ``test #N`` becomes See TEST #N."""
    raw = _clip(text)
    if not raw:
        return ""
    needle = _NEEDLE_ONLY.match(raw)
    if needle:
        return f"See TEST #{needle.group(1)}"
    return raw


def tally_cleared(ruled_out: list[str]) -> list[str]:
    """Deduped cleared checks; drop a needle when a richer line names that TEST."""
    labels = [display_check_label(item) for item in ruled_out]
    labels = [item for item in labels if item]
    covered: set[str] = set()
    for label in labels:
        if not _NEEDLE_ONLY.match(label):
            covered.update(procedure_needles(label))
    out: list[str] = []
    seen: set[str] = set()
    for label in labels:
        match = _NEEDLE_ONLY.match(label)
        if match and f"test #{match.group(1)}" in covered:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def tally_offered(assistant: str, cleared: list[str]) -> list[str]:
    """This turn's numbered checks (or a See TEST pointer), minus cleared."""
    items = checks_from_assistant(assistant)
    if not items:
        items = [display_check_label(needle) for needle in procedure_needles(assistant)]
    labels = tally_cleared(items)
    cleared_keys = {item.lower() for item in cleared}
    cleared_tests: set[str] = set()
    for item in cleared:
        cleared_tests.update(procedure_needles(item))
    out: list[str] = []
    for label in labels:
        if label.lower() in cleared_keys:
            continue
        needles = set(procedure_needles(label))
        if needles and needles <= cleared_tests:
            continue
        out.append(label)
    return out


def session_tally(
    board: DiagnosticBoard,
    citations: list | None = None,
    fallback_citations: list | None = None,
    assistant: str = "",
) -> dict[str, object]:
    """Computed UI payload — does not change the stored board (ADR-0044)."""
    rows = list(citations or []) or list(fallback_citations or [])
    cite_index: int | None = None
    cite_label = ""
    cite_doc = ""
    cite_page: int | None = None
    for cite in rows:
        if isinstance(cite, dict):
            idx = cite.get("index")
            if idx is None:
                continue
            cite_index = int(idx)
            cite_label = str(cite.get("label") or "")
            cite_doc = str(cite.get("doc_id") or "")
            page = cite.get("page")
            cite_page = int(page) if page is not None else None
        else:
            idx = getattr(cite, "index", None)
            if idx is None:
                continue
            cite_index = int(idx)
            cite_label = str(getattr(cite, "label", "") or "")
            cite_doc = str(getattr(cite, "doc_id", "") or "")
            page = getattr(cite, "page", None)
            cite_page = int(page) if page is not None else None
        break
    closed = board.phase == "close"
    cleared = tally_cleared(board.ruled_out)
    nxt = "" if closed else display_check_label(board.next_check)
    offered = [] if closed else tally_offered(assistant, cleared)
    return {
        "symptom": board.symptom_anchor,
        "cleared": cleared,
        "offered": offered,
        "next": nxt,
        "closed": closed,
        "citation_index": cite_index,
        "citation_label": cite_label,
        "citation_doc_id": cite_doc,
        "citation_page": cite_page,
    }


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
