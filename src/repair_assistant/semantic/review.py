"""Human review operations over a candidate semantic version (ADR-0049).

Every edit here rebuilds ``source_text`` from a thin PDF extract of the page
range, so a reviewer can change *where* a boundary sits but never *what* the
document says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from repair_assistant.semantic import store as semantic_store
from repair_assistant.semantic.segment import ProposedUnit
from repair_assistant.semantic.units import (
    ORIGIN_HUMAN,
    REVIEW_APPROVED,
    REVIEW_EDITED,
    SemanticUnit,
    resegment_unit,
    slugify,
)
from repair_assistant.semantic.validate import (
    ValidationIssue,
    ValidationReport,
    validate,
)

if TYPE_CHECKING:
    from repair_assistant.ingest.store import Database


class ReviewError(ValueError):
    """A review edit that cannot be applied to the PDF markers."""


@dataclass(frozen=True)
class EditOutcome:
    changed: list[SemanticUnit]
    removed: list[str]

    @property
    def changed_keys(self) -> list[str]:
        return [u.unit_key for u in self.changed]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_marker(unit: SemanticUnit) -> tuple[int, int, float, float]:
    """Recover page + y markers from a unit."""
    start_page = int(unit.page_start or 0)
    end_page = int(unit.page_end or start_page)
    start_y = float(unit.start_y)
    end_y = float(unit.end_y)
    if unit.source_span and len(unit.source_span) >= 2:
        try:
            a, b = unit.source_span[0], unit.source_span[1]
            if a.startswith("p") and "@" in a:
                start_page = int(a[1 : a.index("@")])
                start_y = float(a.split("@", 1)[1])
            if b.startswith("p") and "@" in b:
                end_page = int(b[1 : b.index("@")])
                end_y = float(b.split("@", 1)[1])
        except (TypeError, ValueError):
            pass
    if start_page < 1 or end_page < start_page:
        raise ReviewError(f"{unit.unit_key}: missing page markers")
    return start_page, end_page, start_y, end_y


def _record(unit: SemanticUnit, action: str, **detail: Any) -> None:
    unit.edits = [*unit.edits, {"action": action, "at": _now(), **detail}]


def review_issues(
    units: list[SemanticUnit],
    *,
    window_start: int,
    window_end: int,
) -> ValidationReport:
    """Re-run boundary validation over the current, human-edited unit set."""
    if not units:
        return ValidationReport(issues=[ValidationIssue("no_units", "no units remain")])
    proposed = []
    for unit in units:
        try:
            start, end, start_y, end_y = parse_marker(unit)
        except ReviewError as exc:
            return ValidationReport(
                issues=[ValidationIssue("unknown_page", str(exc))]
            )
        proposed.append(
            ProposedUnit(
                start_page=start,
                end_page=end,
                start_y=start_y,
                end_y=end_y,
                title=unit.title,
                unit_type=unit.unit_type,
                rationale=unit.rationale,
                review_flag=unit.review_flag,
                review_note=unit.review_note,
            )
        )
    return validate(
        proposed, window_start=window_start, window_end=window_end
    )


def move_boundary(
    db: Database,
    version_id: int,
    unit: SemanticUnit,
    *,
    pdf_path: Path,
    start_page: int | None = None,
    end_page: int | None = None,
    start_y: float | None = None,
    end_y: float | None = None,
    title: str | None = None,
    unit_type: str | None = None,
) -> EditOutcome:
    """Retitle a unit or move where it starts and stops on the PDF."""
    cur_start, cur_end, cur_sy, cur_ey = parse_marker(unit)
    before = {
        "start_page": cur_start,
        "end_page": cur_end,
        "start_y": cur_sy,
        "end_y": cur_ey,
    }
    new_start = cur_start if start_page is None else int(start_page)
    new_end = cur_end if end_page is None else int(end_page)
    new_sy = cur_sy if start_y is None else float(start_y)
    new_ey = cur_ey if end_y is None else float(end_y)

    moved = resegment_unit(
        unit,
        pdf_path=pdf_path,
        start_page=new_start,
        end_page=new_end,
        start_y=new_sy,
        end_y=new_ey,
        title=title,
        unit_type=unit_type,
    )
    if (
        moved.content_hash == unit.content_hash
        and moved.title == unit.title
        and moved.unit_type == unit.unit_type
    ):
        return EditOutcome(changed=[], removed=[])

    _record(
        moved,
        "move_boundary",
        before=before,
        after={
            "start_page": moved.page_start,
            "end_page": moved.page_end,
            "start_y": moved.start_y,
            "end_y": moved.end_y,
        },
        title=moved.title if moved.title != unit.title else None,
        unit_type=moved.unit_type if moved.unit_type != unit.unit_type else None,
    )
    semantic_store.update_unit(db, version_id, moved)
    return EditOutcome(changed=[moved], removed=[])


def _marker_key(unit: SemanticUnit) -> tuple[int, float, int]:
    start, _end, start_y, _end_y = parse_marker(unit)
    return (start, start_y, unit.ordinal)


def _span_empty(start_page: int, start_y: float, end_page: int, end_y: float) -> bool:
    return (start_page, start_y) >= (end_page, end_y)


def resize_unit_pushing_neighbors(
    db: Database,
    version_id: int,
    unit: SemanticUnit,
    *,
    pdf_path: Path,
    start_page: int | None = None,
    end_page: int | None = None,
    start_y: float | None = None,
    end_y: float | None = None,
    title: str | None = None,
    unit_type: str | None = None,
) -> EditOutcome:
    """Resize a unit; push adjacent neighbors; absorb any that collapse.

    Matches the review board mental model: expand this marker and the next
    shrinks until it vanishes into a merge.
    """
    cur_start, cur_end, cur_sy, cur_ey = parse_marker(unit)
    new_start = cur_start if start_page is None else int(start_page)
    new_end = cur_end if end_page is None else int(end_page)
    new_sy = cur_sy if start_y is None else float(start_y)
    new_ey = cur_ey if end_y is None else float(end_y)
    if _span_empty(new_start, new_sy, new_end, new_ey):
        raise ReviewError(f"{unit.unit_key}: a unit cannot end before it starts")

    boundary_changed = (
        new_start != cur_start
        or new_end != cur_end
        or new_sy != cur_sy
        or new_ey != cur_ey
    )
    if not boundary_changed:
        return move_boundary(
            db,
            version_id,
            unit,
            pdf_path=pdf_path,
            title=title,
            unit_type=unit_type,
        )

    before = {
        "start_page": cur_start,
        "end_page": cur_end,
        "start_y": cur_sy,
        "end_y": cur_ey,
    }
    moved = resegment_unit(
        unit,
        pdf_path=pdf_path,
        start_page=new_start,
        end_page=new_end,
        start_y=new_sy,
        end_y=new_ey,
        title=title,
        unit_type=unit_type,
    )
    _record(
        moved,
        "resize_push",
        before=before,
        after={
            "start_page": moved.page_start,
            "end_page": moved.page_end,
            "start_y": moved.start_y,
            "end_y": moved.end_y,
        },
    )
    semantic_store.update_unit(db, version_id, moved)

    changed: list[SemanticUnit] = [moved]
    removed: list[str] = []
    path = Path(pdf_path)

    def _ordered_others() -> list[SemanticUnit]:
        return sorted(
            (
                u
                for u in semantic_store.list_units(db, version_id)
                if u.unit_key != moved.unit_key
            ),
            key=_marker_key,
        )

    # Push / absorb units after this one.
    while True:
        ms, me, msy, mey = parse_marker(moved)
        nxt = None
        for u in _ordered_others():
            us, _ue, usy, _uey = parse_marker(u)
            if (us, usy) >= (ms, msy):
                nxt = u
                break
        if nxt is None:
            break
        ns, ne, nsy, ney = parse_marker(nxt)
        if (me, mey) <= (ns, nsy):
            break
        if (me, mey) >= (ne, ney) or _span_empty(me, mey, ne, ney):
            outcome = merge_units(db, version_id, moved, nxt, pdf_path=path)
            moved = outcome.changed[0]
            changed = [moved]
            removed.extend(outcome.removed)
            continue
        pushed = resegment_unit(
            nxt,
            pdf_path=path,
            start_page=me,
            end_page=ne,
            start_y=mey,
            end_y=ney,
        )
        _record(pushed, "pushed_by", by=moved.unit_key)
        semantic_store.update_unit(db, version_id, pushed)
        changed.append(pushed)
        break

    # Push / absorb the unit immediately before this one.
    while True:
        ms, me, msy, mey = parse_marker(moved)
        prev = None
        for u in _ordered_others():
            us, _ue, usy, _uey = parse_marker(u)
            if (us, usy) < (ms, msy):
                prev = u
            else:
                break
        if prev is None:
            break
        ps, pe, psy, pey = parse_marker(prev)
        if (ms, msy) >= (pe, pey):
            break
        if (ms, msy) <= (ps, psy) or _span_empty(ps, psy, ms, msy):
            outcome = merge_units(db, version_id, moved, prev, pdf_path=path)
            moved = outcome.changed[0]
            changed = [c for c in changed if c.unit_key not in set(outcome.removed)]
            if not any(c.unit_key == moved.unit_key for c in changed):
                changed.insert(0, moved)
            else:
                changed = [moved if c.unit_key == moved.unit_key else c for c in changed]
            removed.extend(outcome.removed)
            continue
        pushed = resegment_unit(
            prev,
            pdf_path=path,
            start_page=ps,
            end_page=ms,
            start_y=psy,
            end_y=msy,
        )
        _record(pushed, "pushed_by", by=moved.unit_key)
        semantic_store.update_unit(db, version_id, pushed)
        changed.append(pushed)
        break

    return EditOutcome(changed=changed, removed=removed)


def split_unit(
    db: Database,
    version_id: int,
    unit: SemanticUnit,
    *,
    pdf_path: Path,
    at_page: int,
    at_y: float = 0.0,
    title: str | None = None,
) -> EditOutcome:
    """Cut one unit in two; ``at_page``/``at_y`` starts the second half."""
    start, end, start_y, end_y = parse_marker(unit)
    cut_page = int(at_page)
    cut_y = float(at_y)
    if (cut_page, cut_y) <= (start, start_y) or (cut_page, cut_y) > (end, end_y):
        raise ReviewError(
            f"split point p.{cut_page}@{cut_y} is not inside {unit.unit_key}"
        )

    # Head ends just before the cut on the same page, or on the previous page.
    if cut_y <= 0.0 and cut_page > start:
        head_end, head_ey = cut_page - 1, 1.0
    else:
        head_end, head_ey = cut_page, max(0.0, cut_y)

    first = resegment_unit(
        unit,
        pdf_path=pdf_path,
        start_page=start,
        end_page=head_end,
        start_y=start_y,
        end_y=head_ey,
    )
    _record(first, "split", at_page=cut_page, at_y=cut_y, kept="head")

    existing = {u.unit_key for u in semantic_store.list_units(db, version_id)}
    base = slugify(title or unit.title, fallback="unit")
    key = f"{unit.ordinal + 1:03d}-{base}-b"
    suffix = 2
    while key in existing or key == unit.unit_key:
        key = f"{unit.ordinal + 1:03d}-{base}-b{suffix}"
        suffix += 1

    second = resegment_unit(
        unit,
        pdf_path=pdf_path,
        start_page=cut_page,
        end_page=end,
        start_y=cut_y,
        end_y=end_y,
        title=title or unit.title,
        origin=ORIGIN_HUMAN,
    )
    second.unit_key = key
    second.ordinal = unit.ordinal + 1
    second.id = None
    _record(second, "split", at_page=cut_page, at_y=cut_y, kept="tail")

    semantic_store.update_unit(db, version_id, first)
    created = semantic_store.insert_unit(db, version_id, second)
    # Re-number later units so ordinals stay unique-ish for the UI.
    return EditOutcome(changed=[first, created], removed=[])


def merge_units(
    db: Database,
    version_id: int,
    left: SemanticUnit,
    right: SemanticUnit,
    *,
    pdf_path: Path,
    title: str | None = None,
) -> EditOutcome:
    """Combine two neighbouring units into the left one's key."""
    ls, le, lsy, ley = parse_marker(left)
    rs, re, rsy, rey = parse_marker(right)
    if (rs, rsy) < (ls, lsy):
        left, right = right, left
        ls, le, lsy, ley = parse_marker(left)
        rs, re, rsy, rey = parse_marker(right)
    merged = resegment_unit(
        left,
        pdf_path=pdf_path,
        start_page=min(ls, rs),
        end_page=max(le, re),
        start_y=lsy if ls <= rs else rsy,
        end_y=rey if re >= le else ley,
        title=title or left.title,
        origin=ORIGIN_HUMAN,
    )
    _record(
        merged,
        "merge",
        with_unit=right.unit_key,
        before_left={"start_page": ls, "end_page": le},
        before_right={"start_page": rs, "end_page": re},
    )
    semantic_store.update_unit(db, version_id, merged)
    semantic_store.delete_unit(db, version_id, right.unit_key)
    return EditOutcome(changed=[merged], removed=[right.unit_key])


def add_unit(
    db: Database,
    version_id: int,
    *,
    pdf_path: Path,
    start_page: int,
    end_page: int,
    title: str,
    unit_type: str = "other",
    start_y: float = 0.0,
    end_y: float = 1.0,
) -> EditOutcome:
    """Insert a human-authored unit over a page range."""
    if start_page > end_page:
        raise ReviewError("a unit cannot end before it starts")
    existing = semantic_store.list_units(db, version_id)
    ordinal = (max((u.ordinal for u in existing), default=-1) + 1)
    base = slugify(title, fallback=slugify(unit_type, fallback="unit"))
    key = f"{ordinal + 1:03d}-{base}"
    used = {u.unit_key for u in existing}
    suffix = 2
    while key in used:
        key = f"{ordinal + 1:03d}-{base}-{suffix}"
        suffix += 1
    blank = SemanticUnit(
        unit_key=key,
        ordinal=ordinal,
        title=title,
        unit_type=unit_type,
        page_start=start_page,
        page_end=end_page,
        section_path=[],
        source_text="",
        source_span=[],
        content_hash="",
        review_status=REVIEW_EDITED,
        origin=ORIGIN_HUMAN,
    )
    created = resegment_unit(
        blank,
        pdf_path=pdf_path,
        start_page=start_page,
        end_page=end_page,
        start_y=start_y,
        end_y=end_y,
        title=title,
        unit_type=unit_type,
        origin=ORIGIN_HUMAN,
    )
    created.unit_key = key
    created.ordinal = ordinal
    created.review_status = REVIEW_EDITED
    _record(
        created,
        "add",
        start_page=start_page,
        end_page=end_page,
        start_y=start_y,
        end_y=end_y,
    )
    stored = semantic_store.insert_unit(db, version_id, created)
    return EditOutcome(changed=[stored], removed=[])


def approve_version_preflight(
    units: list[SemanticUnit],
    *,
    window_start: int,
    window_end: int,
) -> ValidationReport:
    """Refuse approve when markers do not tile the document or OCR is needed."""
    report = review_issues(
        units, window_start=window_start, window_end=window_end
    )
    ocr_blocked = [
        u.unit_key for u in units if u.needs_ocr or not (u.source_text or "").strip()
    ]
    if ocr_blocked:
        report.issues.append(
            ValidationIssue(
                "needs_ocr",
                "units with empty PDF extract need OCR before activate: "
                + ", ".join(ocr_blocked[:8]),
            )
        )
    return report


def set_review_status(
    db: Database,
    version_id: int,
    unit: SemanticUnit,
    status: str,
) -> EditOutcome:
    """Approve (or un-approve) one unit without changing its boundary."""
    if status not in {REVIEW_APPROVED, REVIEW_EDITED, "proposed"}:
        raise ReviewError(f"unknown review status: {status}")
    unit.review_status = status
    _record(unit, "set_review_status", status=status)
    semantic_store.update_unit(db, version_id, unit)
    return EditOutcome(changed=[unit], removed=[])


def remove_unit(
    db: Database,
    version_id: int,
    unit: SemanticUnit | str,
    *_ignored: Any,
) -> EditOutcome:
    key = unit.unit_key if isinstance(unit, SemanticUnit) else str(unit)
    semantic_store.delete_unit(db, version_id, key)
    return EditOutcome(changed=[], removed=[key])
