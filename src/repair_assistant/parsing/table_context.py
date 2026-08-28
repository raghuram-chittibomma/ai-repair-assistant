"""Hierarchical table context for service troubleshooting matrices (ADR-0022).

Two layouts share the same column headers (Problem | Possible cause | Checks & tests)
but chunk differently:

**Guide #1 (``problem_spanned``)** — one problem spans many cause→check rows:
  WON'T POWER UP → Control lock activated → Check control lock LED…
  (empty problem) → No power to washer → Check power at outlet…

**Guide #2 (``group_symptom``)** — group header then symptom-as-problem rows:
  POOR WASH PERFORMANCE (+ refer Use & Care) → Oversuds → numbered checks…

Rules are generic (pattern-based), not document-specific.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.parsing.models import Table

# Column header synonyms (case-insensitive substring match).
_PROBLEM_HDR = ("problem", "symptom", "fault", "condition")
_CAUSE_HDR = ("possible cause", "cause", "reason")
_CHECKS_HDR = ("checks", "tests", "check & test", "checks & test", "action")

_GROUP_NOTE_RE = re.compile(
    r"\b(refer customer|please refer|see use|use & care|use and care)\b",
    re.I,
)
_ALL_CAPS_LINE_RE = re.compile(
    r"^[A-Z][A-Z0-9\s/&\-'’\"]{4,}$",
)
_TROUBLESHOOTING_GUIDE_RE = re.compile(
    r"TROUBLESHOOTING\s+GUIDE\s*#\s*\d+",
    re.I,
)
# Matrix column header — CHECKS may be missing, on the next line, or far right.
_MATRIX_HDR_RE = re.compile(
    r"PROBLEM\s+POSSIBLE\s+CAUSE(?:\s*(?:&?\s*CHECKS?(?:\s*&\s*TESTS?)?)?)?",
    re.I,
)
_MATRIX_HDR_LOOSE_RE = re.compile(
    r"PROBLEM.{0,60}POSSIBLE\s+CAUSE|POSSIBLE\s+CAUSE.{0,60}CHECKS",
    re.I | re.S,
)
# Guide #1 problem anchors (first line of problem cell).
_PROBLEM_ANCHOR_RE = re.compile(
    r"^(?:WON'?T|NO |DOOR |HMI |INCORRECT |LEAKING|VIBRATION|POOR DRY|CLEAN |SANITIZE |"
    r"DRUM |DRY HEATER|WON'T|WONT)",
    re.I,
)
# Guide #2 group titles (category headers inside the matrix).
_GROUP_SYMPTOM_TITLE_RE = re.compile(
    r"(?:PERFORMANCE|LEAKING|NOISE)$",
    re.I,
)
_GROUP_TITLE_TAIL_RE = re.compile(
    r"^(PERFORMANCE|LEAKING|NOISE)\b",
    re.I,
)
_SYMPTOM_ROW_RE = re.compile(
    r"(?:^|(?<=[\n.]))([A-Z][A-Za-z0-9][^.\n]{4,70}\.)",
    re.M,
)
_GUIDE1_PROBLEM_RE = re.compile(
    r"(?:^|\n)((?:WON'?T|NO |DOOR |CLEAN WASHER|INCORRECT WATER|NO BUTTON)"
    r"[A-Z0-9 /&\-'’]{2,}?)(?=\n|\s+[A-Z][a-z]|\.|$)",
    re.M,
)
# LTR extract glues group prefix to first symptom; PERFORMANCE is on the next line
# (often followed by more numbered checks):
#   POOR WASH Oversuds. 1. Verify…
#   PERFORMANCE 2. Excessive…
_GROUP_PREFIX_BEFORE_SYMPTOM_RE = re.compile(
    r"\b((?:POOR\s+WASH|POOR\s+DRY|[A-Z]{3,}(?:\s+[A-Z]{3,}){0,4}))\s+"
    r"([A-Z][a-z][^.\n]{2,60}\.)"  # symptom title
    r"([^\n]*)\n\s*"  # same-line checks
    r"(PERFORMANCE|LEAKING|NOISE)\b",
    re.M,
)
_GROUP_TITLE_WRAP_RE = re.compile(
    r"\b((?:POOR\s+WASH|POOR\s+DRY|[A-Z]{3,}(?:\s+[A-Z]{3,}){0,4}))\s*\n\s*"
    r"(PERFORMANCE|LEAKING|NOISE)\b",
    re.M,
)
_NUMBERED_CHECK_RE = re.compile(r"(?:^|\n)\s*\d+\.\s+\S")
_DEFAULT_HEADERS = ["Problem", "Possible cause", "Checks & tests"]



@dataclass(frozen=True)
class ColumnMap:
    problem: int = 0
    cause: int = 1
    checks: int = 2


@dataclass
class ContextualTableRow:
    """One logical row after hierarchical context is applied."""

    role: str  # group_header | data
    cells: list[str] = field(default_factory=list)
    matrix_kind: str = ""  # problem_spanned | group_symptom
    guide_title: str = ""
    problem_title: str = ""
    problem_detail: str = ""
    group_title: str = ""
    group_note: str = ""
    headers: list[str] = field(default_factory=list)


def is_troubleshooting_matrix(headers: list[str]) -> bool:
    """True for PROBLEM / CAUSE / CHECKS style matrices (not error-code tables)."""
    joined = " ".join(headers).lower()
    if "error" in joined and "code" in joined:
        return False
    has_problem = any(k in joined for k in _PROBLEM_HDR)
    has_checks = any(k in joined for k in _CHECKS_HDR)
    return has_problem and has_checks


def detect_column_map(headers: list[str]) -> ColumnMap:
    lower = [h.lower() for h in headers]

    def _find(candidates: tuple[str, ...], default: int) -> int:
        for i, h in enumerate(lower):
            if any(c in h for c in candidates):
                return i
        return default

    return ColumnMap(
        problem=_find(_PROBLEM_HDR, 0),
        cause=_find(_CAUSE_HDR, 1),
        checks=_find(_CHECKS_HDR, 2),
    )


def extract_guide_title(text: str | None) -> str:
    if not text:
        return ""
    m = _TROUBLESHOOTING_GUIDE_RE.search(text)
    return m.group(0).strip() if m else ""


def _pad_cells(cells: list[str], width: int) -> list[str]:
    out = list(cells)
    while len(out) < width:
        out.append("")
    return out[:width]


def _cell(cells: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(cells):
        return ""
    return (cells[idx] or "").strip()


def split_problem_cell(text: str) -> tuple[str, str]:
    """First line = anchor title; remainder = symptom bullets / IMPORTANT notes."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:])


def problem_anchor_title(text: str) -> str:
    """First line of a problem cell if it looks like a Guide #1 anchor."""
    title, _ = split_problem_cell(text)
    return title if is_problem_anchor(title) else ""


def is_problem_anchor(text: str) -> bool:
    """Guide #1 problem title (WON'T POWER UP, WON'T START CYCLE, …)."""
    line = (text or "").strip().splitlines()[0].strip() if text else ""
    if not line or len(line) < 4:
        return False
    normalized = line.replace("'", "'").replace("'", "'")
    if extract_error_codes(line):
        return False
    if not _ALL_CAPS_LINE_RE.match(normalized.replace(".", "")):
        return False
    if _GROUP_SYMPTOM_TITLE_RE.search(normalized):
        return False
    return bool(_PROBLEM_ANCHOR_RE.match(normalized))


def is_group_symptom_header(cells: list[str], col: ColumnMap) -> bool:
    """Guide #2 group row (POOR WASH PERFORMANCE + optional refer note)."""
    problem = _cell(cells, col.problem)
    cause = _cell(cells, col.cause)
    checks = _cell(cells, col.checks)
    if not problem:
        return False
    if is_problem_anchor(problem):
        return False
    if checks and not _GROUP_NOTE_RE.search(checks):
        return False
    first_line = split_problem_cell(problem)[0]
    if not _ALL_CAPS_LINE_RE.match(first_line.replace(".", "")):
        return False
    if _GROUP_SYMPTOM_TITLE_RE.search(first_line):
        return True
    if _GROUP_NOTE_RE.search(cause or ""):
        return True
    if not cause and not checks:
        return True
    return False


def is_header_repeat_row(cells: list[str], headers: list[str]) -> bool:
    joined = " ".join(c.lower() for c in cells if c)
    hdr = " ".join(h.lower() for h in headers if h)
    return bool(hdr) and joined == hdr


def detect_matrix_kind(table: Table) -> str:
    """Classify table layout from row patterns (per-table, not per-document)."""
    if not is_troubleshooting_matrix(table.headers):
        return ""
    col = detect_column_map(table.headers)
    width = max(len(table.headers), 3)
    group_headers = 0
    spanned_signals = 0
    current_anchor = False

    for row in table.rows:
        cells = _pad_cells(row.cells, width)
        if is_header_repeat_row(cells, table.headers):
            continue
        if not any(c.strip() for c in cells):
            continue
        if is_group_symptom_header(cells, col):
            group_headers += 1
            current_anchor = False
            continue
        problem = _cell(cells, col.problem)
        cause = _cell(cells, col.cause)
        checks = _cell(cells, col.checks)
        if problem and is_problem_anchor(problem):
            current_anchor = True
            if cause or checks:
                spanned_signals += 1
        elif current_anchor and not problem and (cause or checks):
            spanned_signals += 1
        elif problem and (cause or checks) and not is_problem_anchor(problem):
            group_headers += 1  # symptom row under group

    if group_headers and spanned_signals == 0:
        return "group_symptom"
    if spanned_signals:
        return "problem_spanned"
    return "problem_spanned"


def iter_contextual_rows(
    table: Table,
    *,
    guide_title: str = "",
) -> list[ContextualTableRow]:
    """Expand a troubleshooting matrix into context-rich logical rows."""
    headers = list(table.headers)
    if not is_troubleshooting_matrix(headers):
        return []

    col = detect_column_map(headers)
    width = max(len(headers), 3)
    matrix_kind = detect_matrix_kind(table)

    current_problem = ""
    current_problem_detail = ""
    current_group = ""
    current_group_note = ""
    out: list[ContextualTableRow] = []

    for row in table.rows:
        cells = _pad_cells(row.cells, width)
        if is_header_repeat_row(cells, headers):
            continue
        if not any(c.strip() for c in cells):
            continue

        problem = _cell(cells, col.problem)
        cause = _cell(cells, col.cause)
        checks = _cell(cells, col.checks)

        if matrix_kind == "group_symptom" and is_group_symptom_header(cells, col):
            current_group = problem
            current_group_note = cause
            out.append(
                ContextualTableRow(
                    role="group_header",
                    cells=cells,
                    matrix_kind=matrix_kind,
                    guide_title=guide_title,
                    group_title=current_group,
                    group_note=current_group_note,
                    headers=headers,
                )
            )
            continue

        # Guide #1: new problem anchor in problem column.
        if problem and is_problem_anchor(problem):
            title, detail = split_problem_cell(problem)
            current_problem = title
            if detail:
                current_problem_detail = detail
            elif problem == title:
                current_problem_detail = ""

        effective_problem = problem
        effective_detail = current_problem_detail
        if matrix_kind == "problem_spanned":
            if problem and is_problem_anchor(problem):
                effective_problem = split_problem_cell(problem)[0]
                effective_detail = split_problem_cell(problem)[1] or current_problem_detail
            elif not problem and current_problem:
                effective_problem = current_problem
                effective_detail = current_problem_detail
            elif not problem and not current_problem:
                continue

        if not cause and not checks:
            continue

        if matrix_kind == "group_symptom" and not is_group_symptom_header(cells, col):
            out.append(
                ContextualTableRow(
                    role="data",
                    cells=cells,
                    matrix_kind=matrix_kind,
                    guide_title=guide_title,
                    group_title=current_group,
                    group_note=current_group_note,
                    headers=headers,
                )
            )
            continue

        if matrix_kind == "problem_spanned":
            row_cells = list(cells)
            row_cells[col.problem] = effective_problem
            out.append(
                ContextualTableRow(
                    role="data",
                    cells=row_cells,
                    matrix_kind=matrix_kind,
                    guide_title=guide_title,
                    problem_title=effective_problem,
                    problem_detail=effective_detail,
                    headers=headers,
                )
            )

    return out


def format_matrix_row_body(row: ContextualTableRow, col: ColumnMap) -> str:
    """Keyed body for one data row."""
    cells = row.cells
    parts: list[str] = []

    problem = row.problem_title or _cell(cells, col.problem)
    cause = _cell(cells, col.cause)
    checks = _cell(cells, col.checks)

    if problem:
        if row.problem_detail:
            parts.append(f"Problem: {problem} ({row.problem_detail})")
        else:
            parts.append(f"Problem: {problem}")
    if cause:
        parts.append(f"Possible cause: {cause}")
    if checks:
        parts.append(f"Checks & tests: {checks}")
    if not parts:
        parts.append(" | ".join(c for c in cells if c.strip()))
    return " | ".join(parts)


def is_troubleshooting_guide_prose(text: str) -> bool:
    """True when page/section text looks like a troubleshooting matrix in prose.

    Tolerates split headers (CHECKS on another line) and missing CHECKS token —
    common when extractors flatten multi-column matrix pages.
    """
    if not text or len(text) < 80:
        return False
    has_guide = bool(_TROUBLESHOOTING_GUIDE_RE.search(text))
    has_hdr = bool(_MATRIX_HDR_RE.search(text) or _MATRIX_HDR_LOOSE_RE.search(text))
    if has_guide and has_hdr:
        return True
    # Guide present + content signals (anchors or group titles).
    if has_guide and (
        _GROUP_SYMPTOM_TITLE_RE.search(text)
        or re.search(r"\bWON'?T\s+[A-Z]", text, re.I)
        or re.search(r"\bPOOR\s+WASH\b", text, re.I)
    ):
        return True
    return False


def normalize_matrix_prose(text: str) -> str:
    """Repair LTR extraction artifacts common on Whirlpool matrix pages.

    Vertical table rules cause line-wise LTR merges like::

        POOR WASH Oversuds. 1. Verify…
        PERFORMANCE 2. Excessive…

    into a recoverable form::

        POOR WASH PERFORMANCE
        Oversuds. 1. Verify…
        2. Excessive…
    """
    if not text:
        return ""
    t = text.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    # Group prefix glued to first symptom, tail PERFORMANCE on next line.
    # → "POOR WASH PERFORMANCE\nOversuds. 1. …\n2. …"
    t = _GROUP_PREFIX_BEFORE_SYMPTOM_RE.sub(r"\1 \4\n\2\3", t)
    # Clean wrap: "POOR WASH\nPERFORMANCE"
    t = _GROUP_TITLE_WRAP_RE.sub(r"\1 \2", t)
    # Standalone PERFORMANCE line that still has numbered checks after it.
    t = re.sub(
        r"(?m)^(PERFORMANCE|LEAKING|NOISE)\s+(\d+\.\s+)",
        r"\1\n\2",
        t,
    )
    # "Please refer" glued to a numbered check on the same line.
    t = re.sub(
        r"(?mi)^(Please refer)\s+(\d+\.\s+)",
        r"\1\n\2",
        t,
    )
    # Peel "Please refer" / "Use & Care Guide." when glued before a symptom.
    t = re.sub(
        r"(Please refer(?:[^\n.]{0,40})?)\s*\n\s*(Use\s*&\s*Care Guide\.?)\s+"
        r"([A-Z][a-z][^.\n]{2,60}\.)",
        r"\1 \2\n\3",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"(Use\s*&\s*Care Guide\.?)\s+([A-Z][a-z][^.\n]{2,60}\.)",
        r"\1\n\2",
        t,
        flags=re.I,
    )
    return t


def _matrix_body(text: str) -> str:
    """Strip guide title / column headers; return body for row parsing."""
    m = _MATRIX_HDR_RE.search(text) or _MATRIX_HDR_LOOSE_RE.search(text)
    if m:
        return text[m.end() :]
    g = _TROUBLESHOOTING_GUIDE_RE.search(text)
    if g:
        return text[g.end() :]
    return text


def detect_prose_matrix_kind(body: str) -> str:
    """Classify prose body as problem_spanned or group_symptom (same as tables)."""
    group_hits = 0
    spanned_hits = 0
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if _looks_like_group_title(s) or _GROUP_TITLE_TAIL_RE.match(s):
            group_hits += 1
        if is_problem_anchor(s.split(".")[0] if "." in s[:40] else s):
            spanned_hits += 1
        elif _PROBLEM_ANCHOR_RE.match(s):
            spanned_hits += 1
    if group_hits and spanned_hits == 0:
        return "group_symptom"
    if spanned_hits and group_hits == 0:
        return "problem_spanned"
    if group_hits >= spanned_hits:
        return "group_symptom"
    return "problem_spanned"


def _looks_like_group_title(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 6:
        return False
    upper = t.upper()
    skip = (
        "PROBLEM POSSIBLE",
        "FOR SERVICE TECHNICIAN",
        "FOR SERVICE TECH",
        "TROUBLESHOOTING GUIDE",
        "CHECKS & TESTS",
        "CHECKS AND TESTS",
        "DO NOT REMOVE",
    )
    if any(p in upper for p in skip):
        return False
    if is_problem_anchor(t):
        return False
    # Accept "POOR WASH PERFORMANCE" and bare "POOR WASH" (pre-normalize).
    if _GROUP_SYMPTOM_TITLE_RE.search(t.replace(".", "")):
        return bool(_ALL_CAPS_LINE_RE.match(t.replace(".", "")))
    if re.match(r"^(POOR\s+WASH|POOR\s+DRY)\s*$", t, re.I):
        return True
    return bool(_ALL_CAPS_LINE_RE.match(t.replace(".", ""))) and len(t) >= 10


def _is_symptom_title(text: str) -> bool:
    """Guide #2 symptom cell: short sentence-case title ending with '.'."""
    t = (text or "").strip()
    if not t.endswith(".") or len(t) < 5 or len(t) > 80:
        return False
    if _GROUP_NOTE_RE.search(t):
        return False
    if t.upper() == t and len(t) > 8:
        return False
    if is_problem_anchor(t):
        return False
    if re.match(r"^\d+\.\s", t):
        return False
    if t.lower().startswith("see "):
        return False
    # Reject ALL-CAPS problem leads: "NO BUTTON SOUND Button sound…"
    words = t.rstrip(".").split()
    if len(words) >= 2 and words[0].isupper() and len(words[0]) > 1 and words[1].isupper():
        return False
    if _PROBLEM_ANCHOR_RE.match(t):
        return False
    # Prefer title-ish: starts with capital letter.
    return bool(re.match(r"^[A-Z][A-Za-z0-9]", t))


def parse_troubleshooting_prose(text: str) -> list[ContextualTableRow]:
    """Split matrix prose into the same ContextualTableRow model as tables.

    Used when PDF extractors miss table structure. Pattern-based for all docs —
    not document- or page-specific.

    A single troubleshooting page may mix Guide #1 anchors (ALL-CAPS problems)
    and Guide #2 groups (POOR WASH PERFORMANCE + sentence-case symptoms). The
    unified walker handles both; pure Guide #1 pages use the spanned parser.
    """
    if not is_troubleshooting_guide_prose(text):
        return []

    guide_title = extract_guide_title(text) or ""
    headers = list(_DEFAULT_HEADERS)
    col = detect_column_map(headers)
    normalized = normalize_matrix_prose(text)
    body = _matrix_body(normalized)

    has_groups = bool(
        _GROUP_SYMPTOM_TITLE_RE.search(body)
        or re.search(r"\bPOOR\s+WASH\b|\bPOOR\s+DRY\b", body, re.I)
    )
    if has_groups:
        rows = _parse_matrix_prose_unified(body, headers, col, guide_title)
        if rows:
            return rows

    kind = detect_prose_matrix_kind(body)
    if kind == "problem_spanned":
        rows = _parse_guide1_prose(body, headers, col, guide_title)
        if rows:
            return rows
    return _parse_matrix_prose_unified(body, headers, col, guide_title)


def _parse_matrix_prose_unified(
    body: str,
    headers: list[str],
    col: ColumnMap,
    guide_title: str,
) -> list[ContextualTableRow]:
    """Walk matrix prose handling group headers, ALL-CAPS problems, and symptoms."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    group_title = ""
    group_note = ""
    pending_group: list[str] = []
    current_problem = ""
    current_detail = ""
    out: list[ContextualTableRow] = []

    def _flush_group_pending() -> None:
        nonlocal group_title, pending_group
        if not pending_group:
            return
        joined = " ".join(pending_group)
        pending_group = []
        if _looks_like_group_title(joined) or _GROUP_SYMPTOM_TITLE_RE.search(joined):
            group_title = joined

    def _emit_data(*, problem: str, cause: str, checks: str, kind: str, detail: str = "") -> None:
        cells = ["", "", ""]
        cells[col.problem] = problem
        cells[col.cause] = cause
        cells[col.checks] = checks
        out.append(
            ContextualTableRow(
                role="data",
                cells=cells,
                matrix_kind=kind,
                guide_title=guide_title,
                problem_title=problem if kind == "problem_spanned" else "",
                problem_detail=detail if kind == "problem_spanned" else "",
                group_title=group_title if kind == "group_symptom" else "",
                group_note=group_note if kind == "group_symptom" else "",
                headers=headers,
            )
        )

    i = 0
    while i < len(lines):
        line = lines[i]

        if _looks_like_group_title(line) and _GROUP_SYMPTOM_TITLE_RE.search(line):
            _flush_group_pending()
            group_title = line
            group_note = ""
            current_problem = ""
            i += 1
            continue

        if re.match(r"^(POOR\s+WASH|POOR\s+DRY)$", line, re.I) or (
            _ALL_CAPS_LINE_RE.match(line.replace(".", ""))
            and not _GROUP_NOTE_RE.search(line)
            and not _is_symptom_title(line)
            and not re.match(r"^\d+\.", line)
            and not _PROBLEM_ANCHOR_RE.match(line)
            and len(line) >= 6
            and line == line.upper()
            and not group_title
        ):
            # Only buffer ALL-CAPS as group-prefix when it looks like a category,
            # not a problem anchor (those are handled below).
            if re.match(r"^(POOR\s+WASH|POOR\s+DRY)$", line, re.I) or (
                len(line.split()) <= 4 and not _PROBLEM_ANCHOR_RE.match(line)
            ):
                pending_group.append(line)
                i += 1
                continue

        if _GROUP_TITLE_TAIL_RE.match(line):
            pending_group.append(_GROUP_TITLE_TAIL_RE.match(line).group(1))
            rest = _GROUP_TITLE_TAIL_RE.sub("", line).strip()
            _flush_group_pending()
            current_problem = ""
            if rest:
                lines.insert(i + 1, rest)
            i += 1
            continue

        if _GROUP_NOTE_RE.search(line) and not _is_symptom_title(line) and not re.match(
            r"^\d+\.", line
        ):
            # "Use & Care Guide. Incorrect water level. See…" — peel trailing symptom.
            peeled = re.match(
                r"^(.*?\b(?:Use\s*&\s*Care Guide|Please refer)[^.]*\.)\s+"
                r"([A-Z][a-z].+)$",
                line,
                re.I,
            )
            if peeled and _is_symptom_title(
                re.match(r"^([^.]+\.)", peeled.group(2)).group(1)
                if re.match(r"^([^.]+\.)", peeled.group(2))
                else ""
            ):
                note = peeled.group(1).strip()
                group_note = (group_note + " " + note).strip() if group_note else note
                lines.insert(i + 1, peeled.group(2).strip())
                i += 1
                continue
            group_note = (group_note + " " + line).strip() if group_note else line
            if i + 1 < len(lines) and re.search(r"use\s*&\s*care", lines[i + 1], re.I):
                group_note = (group_note + " " + lines[i + 1]).strip()
                i += 2
                continue
            i += 1
            continue

        # Sentence-case symptom under a group (Guide #2).
        symptom_match = re.match(
            r"^([A-Z][A-Za-z0-9][^.\n]{2,70}\.)\s*(.*)$",
            line,
        )
        if symptom_match and _is_symptom_title(symptom_match.group(1)):
            _flush_group_pending()
            problem = symptom_match.group(1).strip()
            checks_parts: list[str] = []
            rest = symptom_match.group(2).strip()
            if rest:
                checks_parts.append(rest)
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if _looks_like_group_title(nxt) and _GROUP_SYMPTOM_TITLE_RE.search(nxt):
                    break
                if re.match(r"^(POOR\s+WASH|POOR\s+DRY)$", nxt, re.I):
                    break
                if _GROUP_TITLE_TAIL_RE.match(nxt) and not re.match(r"^\d+\.", nxt):
                    break
                if _GROUP_NOTE_RE.search(nxt) and not re.match(r"^\d+\.", nxt):
                    break
                nxt_sym = re.match(r"^([A-Z][A-Za-z0-9][^.\n]{2,70}\.)\s*(.*)$", nxt)
                if nxt_sym and _is_symptom_title(nxt_sym.group(1)):
                    break
                if _PROBLEM_ANCHOR_RE.match(nxt) and nxt == nxt.upper():
                    break
                checks_parts.append(nxt)
                i += 1
            _emit_data(
                problem=problem,
                cause="",
                checks=" ".join(checks_parts).strip(),
                kind="group_symptom",
            )
            continue

        # ALL-CAPS problem anchor with optional same-line cause/check (Guide #1 style).
        anchor_match = re.match(
            r"^((?:WON'?T|NO |DOOR |CLEAN |INCORRECT |HMI |LEAKING |VIBRATION |"
            r"POOR DRY |DRUM |SANITIZE )[A-Z0-9 /&\-]{2,}?)\s*(.*)$",
            line,
        )
        if anchor_match and (
            is_problem_anchor(anchor_match.group(1).strip())
            or _PROBLEM_ANCHOR_RE.match(anchor_match.group(1).strip())
        ):
            _flush_group_pending()
            title = " ".join(anchor_match.group(1).split())
            # Continuation ALL-CAPS lines (INCORRECT WATER / TEMPERATURE).
            i += 1
            while i < len(lines) and _ALL_CAPS_LINE_RE.match(
                lines[i].replace(".", "")
            ) and not _GROUP_NOTE_RE.search(lines[i]) and not re.match(r"^\d+\.", lines[i]):
                if _GROUP_TITLE_TAIL_RE.match(lines[i]):
                    break
                if _is_symptom_title(lines[i]):
                    break
                # Stop if next line looks like a new anchor.
                if _PROBLEM_ANCHOR_RE.match(lines[i]) and lines[i] != lines[i].upper():
                    break
                # Append pure ALL-CAPS title continuations only.
                if lines[i] == lines[i].upper() and not re.search(
                    r"[a-z]", lines[i]
                ):
                    title = title + " " + lines[i]
                    i += 1
                    continue
                break
            current_problem = title
            current_detail = ""
            rest = anchor_match.group(2).strip()
            # Collect cause/check until next anchor/group/symptom.
            parts: list[str] = []
            if rest:
                parts.append(rest)
            while i < len(lines):
                nxt = lines[i]
                if _looks_like_group_title(nxt) and _GROUP_SYMPTOM_TITLE_RE.search(nxt):
                    break
                if re.match(r"^(POOR\s+WASH|POOR\s+DRY)$", nxt, re.I):
                    break
                if _PROBLEM_ANCHOR_RE.match(nxt) and (
                    is_problem_anchor(nxt) or nxt.startswith(("WON", "NO ", "CLEAN ", "INCORRECT "))
                ):
                    # New anchor — but allow bullet detail lines.
                    if nxt.lstrip().startswith(("•", "-", "*")):
                        current_detail = (current_detail + "\n" + nxt).strip()
                        i += 1
                        continue
                    if nxt == nxt.upper() or is_problem_anchor(nxt.split(".")[0]):
                        break
                if _is_symptom_title(nxt.split("  ")[0] if "  " in nxt else nxt[:80]):
                    # Only break on clear symptoms when we already have a group.
                    if group_title and _is_symptom_title(
                        re.match(r"^([^.]+\.)", nxt).group(1) if re.match(r"^([^.]+\.)", nxt) else ""
                    ):
                        break
                if nxt.lstrip().startswith(("•", "-", "*")):
                    current_detail = (current_detail + "\n" + nxt).strip()
                    i += 1
                    continue
                parts.append(nxt)
                i += 1
            blob = " ".join(parts).strip()
            # Prefer cause/check sentence pairs; else whole blob as checks.
            pairs = re.findall(
                r"([A-Z][^.?\n]{4,100}\.)\s+((?:Check |See |Make |Ensure |Run |Unplug )"
                r"[^.?\n]{4,}(?:\.|$))",
                blob,
                re.I,
            )
            if pairs:
                for cause, checks in pairs:
                    _emit_data(
                        problem=current_problem,
                        cause=cause.strip(),
                        checks=checks.strip(),
                        kind="problem_spanned",
                        detail=current_detail,
                    )
            elif blob:
                # Split "Cause text. Check text." if possible.
                m = re.match(
                    r"^([A-Z].{4,100}?\.)\s+(.*)$",
                    blob,
                )
                if m and not m.group(1).lower().startswith("see "):
                    _emit_data(
                        problem=current_problem,
                        cause=m.group(1).strip(),
                        checks=m.group(2).strip(),
                        kind="problem_spanned",
                        detail=current_detail,
                    )
                else:
                    _emit_data(
                        problem=current_problem,
                        cause="",
                        checks=blob,
                        kind="problem_spanned",
                        detail=current_detail,
                    )
            continue

        i += 1

    if not out:
        return _parse_prose_symptom_segment(body, headers, col, "", "", guide_title)
    return out


def _parse_guide2_prose(
    body: str,
    headers: list[str],
    col: ColumnMap,
    guide_title: str,
) -> list[ContextualTableRow]:
    """Backward-compatible entry → unified walker."""
    return _parse_matrix_prose_unified(body, headers, col, guide_title)


def _parse_guide1_prose(
    body: str,
    headers: list[str],
    col: ColumnMap,
    guide_title: str,
) -> list[ContextualTableRow]:
    anchors = list(_GUIDE1_PROBLEM_RE.finditer(body))
    if not anchors:
        return []
    out: list[ContextualTableRow] = []
    for i, am in enumerate(anchors):
        problem_title = " ".join(am.group(1).split())
        if not is_problem_anchor(problem_title) and not _PROBLEM_ANCHOR_RE.match(
            problem_title
        ):
            # Multi-line titles like "CLEAN WASHER LED FLASHING..." may need join.
            if not _ALL_CAPS_LINE_RE.match(problem_title.replace(".", "")):
                continue
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(body)
        segment = body[am.end() : end].strip()
        title = problem_title
        # Bullet symptom detail lines under the anchor.
        detail_lines = [
            ln.strip()
            for ln in segment.splitlines()
            if ln.strip().startswith(("•", "-", "*", "\uf0d8"))
        ]
        detail = "\n".join(detail_lines)
        pairs = re.findall(
            r"([A-Z][^.?\n]{4,100}\.)\s+((?:Check |See TEST|See )[^.?\n]{4,}(?:\.|$))",
            segment,
            re.I,
        )
        if not pairs:
            pairs = re.findall(
                r"([A-Z][^.?\n]{4,100}\.)\s+([A-Z][^.?\n]{4,}\.)",
                segment,
            )
        for cause, checks in pairs:
            c = cause.strip()
            k = checks.strip()
            if _is_symptom_title(c) and not k.lower().startswith(("check", "see")):
                continue
            cells = ["", "", ""]
            cells[col.problem] = title
            cells[col.cause] = c
            cells[col.checks] = k
            out.append(
                ContextualTableRow(
                    role="data",
                    cells=cells,
                    matrix_kind="problem_spanned",
                    guide_title=guide_title,
                    problem_title=title,
                    problem_detail=detail,
                    headers=headers,
                )
            )
    return out


def _parse_prose_symptom_segment(
    segment: str,
    headers: list[str],
    col: ColumnMap,
    group_title: str,
    group_note: str,
    guide_title: str,
) -> list[ContextualTableRow]:
    if not segment.strip():
        return []
    out: list[ContextualTableRow] = []
    starts = [m.start(1) for m in _SYMPTOM_ROW_RE.finditer(segment)]
    if not starts:
        return []
    starts.append(len(segment))
    for i, start in enumerate(starts[:-1]):
        end = starts[i + 1]
        chunk = segment[start:end].strip()
        dot = chunk.find(".")
        if dot <= 0:
            continue
        problem = chunk[: dot + 1].strip()
        checks = chunk[dot + 1 :].strip()
        if not _is_symptom_title(problem):
            continue
        cells = ["", "", ""]
        cells[col.problem] = problem
        cells[col.checks] = checks
        out.append(
            ContextualTableRow(
                role="data",
                cells=cells,
                matrix_kind="group_symptom",
                guide_title=guide_title,
                group_title=group_title,
                group_note=group_note,
                headers=headers,
            )
        )
    return out


# Backward-compatible alias used in tests.
is_group_header_row = is_group_symptom_header


__all__ = [
    "ColumnMap",
    "ContextualTableRow",
    "detect_column_map",
    "detect_matrix_kind",
    "detect_prose_matrix_kind",
    "extract_guide_title",
    "format_matrix_row_body",
    "is_group_header_row",
    "is_group_symptom_header",
    "is_problem_anchor",
    "is_troubleshooting_guide_prose",
    "is_troubleshooting_matrix",
    "iter_contextual_rows",
    "normalize_matrix_prose",
    "parse_troubleshooting_prose",
    "problem_anchor_title",
    "split_problem_cell",
]

