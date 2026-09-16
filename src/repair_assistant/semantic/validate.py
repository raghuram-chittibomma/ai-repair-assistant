"""Deterministic validation of PDF page-range proposals (ADR-0049)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repair_assistant.semantic.segment import ProposedUnit

UNKNOWN_PAGE = "unknown_page"
REVERSED_BOUNDARY = "reversed_boundary"
OVERLAPPING_UNITS = "overlapping_units"
COVERAGE_GAP = "coverage_gap"
EMPTY_UNIT = "empty_unit"
DUPLICATE_UNIT = "duplicate_unit"
NO_UNITS = "no_units"
INVALID_Y = "invalid_y"
DROPPED_STRUCTURAL_ANCHOR = "dropped_structural_anchor"
UNKNOWN_ANCHOR = "unknown_anchor"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    detail: str
    unit_index: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "unit_index": self.unit_index}


@dataclass(frozen=True)
class ValidatedSpan:
    start_page: int
    end_page: int
    start_y: float
    end_y: float
    title: str
    unit_type: str
    rationale: str = ""
    origin: str = "llm"
    review_flag: str = "none"
    review_note: str = ""
    section_path: tuple[str, ...] = ()

    @property
    def page_start(self) -> int:
        return self.start_page

    @property
    def page_end(self) -> int:
        return self.end_page


@dataclass
class ValidationReport:
    spans: list[ValidatedSpan] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "units": len(self.spans),
            "issues": [i.to_json() for i in self.issues],
            "repairs": list(self.repairs),
        }


def _clamp_y(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sort_key(span: ValidatedSpan) -> tuple[int, float, int, float]:
    return (span.start_page, span.start_y, span.end_page, span.end_y)


def validate(
    proposed: list[ProposedUnit],
    *,
    window_start: int,
    window_end: int,
) -> ValidationReport:
    """Check a proposal against the page window the model was given."""
    report = ValidationReport()
    if window_start < 1 or window_end < window_start:
        report.issues.append(
            ValidationIssue(NO_UNITS, "document window has no pages")
        )
        return report
    if not proposed:
        report.issues.append(ValidationIssue(NO_UNITS, "proposal contains no units"))
        return report

    resolved: list[ValidatedSpan] = []
    for index, unit in enumerate(proposed):
        start = int(unit.start_page)
        end = int(unit.end_page)
        if unit.start_y < -0.05 or unit.start_y > 1.05 or unit.end_y < -0.05 or unit.end_y > 1.05:
            report.issues.append(
                ValidationIssue(INVALID_Y, f"unit {index} has y outside [0,1]", index)
            )
            continue
        start_y = _clamp_y(unit.start_y)
        end_y = _clamp_y(unit.end_y)
        if start < window_start or end > window_end or start < 1:
            report.issues.append(
                ValidationIssue(
                    UNKNOWN_PAGE,
                    f"pages {start}-{end} outside window {window_start}-{window_end}",
                    index,
                )
            )
            continue
        if start > end or (start == end and start_y > end_y):
            report.issues.append(
                ValidationIssue(
                    REVERSED_BOUNDARY,
                    f"unit {index} ends before it starts ({start}@{start_y}..{end}@{end_y})",
                    index,
                )
            )
            continue
        resolved.append(
            ValidatedSpan(
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

    resolved.sort(key=_sort_key)

    seen: set[tuple[int, float, int, float]] = set()
    for span in resolved:
        key = (span.start_page, span.start_y, span.end_page, span.end_y)
        if key in seen:
            report.issues.append(
                ValidationIssue(
                    DUPLICATE_UNIT,
                    f"two units cover pp.{span.start_page}-{span.end_page}",
                )
            )
        seen.add(key)

    ordered = list(resolved)
    for left, right in zip(ordered, ordered[1:], strict=False):
        # Strict overlap (touching end==next start is allowed).
        if (right.start_page, right.start_y) < (left.end_page, left.end_y):
            report.issues.append(
                ValidationIssue(
                    OVERLAPPING_UNITS,
                    f"pp.{right.start_page}-{right.end_page} overlaps "
                    f"pp.{left.start_page}-{left.end_page}",
                )
            )

    if resolved:
        covered_pages: set[int] = set()
        for span in resolved:
            covered_pages.update(range(span.start_page, span.end_page + 1))
        missing = [
            p for p in range(window_start, window_end + 1) if p not in covered_pages
        ]
        if missing:
            report.issues.append(
                ValidationIssue(
                    COVERAGE_GAP,
                    f"{len(missing)} page(s) belong to no unit: "
                    + ", ".join(str(p) for p in missing[:8])
                    + (" ..." if len(missing) > 8 else ""),
                )
            )

    report.spans = resolved
    return report


def absorb_gaps(
    report: ValidationReport,
    *,
    window_start: int,
    window_end: int,
) -> ValidationReport:
    """Extend neighbouring units to cover missing pages. Recorded repair."""
    unrepairable = report.codes() - {COVERAGE_GAP}
    if unrepairable or not report.spans:
        return report

    spans = sorted(report.spans, key=_sort_key)
    covered: set[int] = set()
    for span in spans:
        covered.update(range(span.start_page, span.end_page + 1))
    missing = [p for p in range(window_start, window_end + 1) if p not in covered]
    if not missing:
        return report

    bounds = [[s.start_page, s.end_page, s.start_y, s.end_y] for s in spans]
    for page in missing:
        target = None
        for position, (start, end, _sy, _ey) in enumerate(bounds):
            if end < page:
                target = position
            elif start > page:
                break
        if target is None:
            bounds[0][0] = min(bounds[0][0], page)
            bounds[0][2] = 0.0
        else:
            bounds[target][1] = max(bounds[target][1], page)
            bounds[target][3] = 1.0

    grown = [
        ValidatedSpan(
            start_page=start,
            end_page=end,
            start_y=start_y,
            end_y=end_y,
            title=span.title,
            unit_type=span.unit_type,
            rationale=span.rationale,
            origin="llm_edited",
            review_flag=span.review_flag,
            review_note=span.review_note,
            section_path=span.section_path,
        )
        for span, (start, end, start_y, end_y) in zip(spans, bounds, strict=True)
    ]

    repaired = ValidationReport(spans=grown, issues=[], repairs=list(report.repairs))
    repaired.repairs.append(
        f"absorbed {len(missing)} uncovered page(s) into the neighbouring unit"
    )
    recheck = validate(
        [
            ProposedUnit(
                start_page=s.start_page,
                end_page=s.end_page,
                start_y=s.start_y,
                end_y=s.end_y,
                title=s.title,
                unit_type=s.unit_type,
            )
            for s in grown
        ],
        window_start=window_start,
        window_end=window_end,
    )
    if recheck.ok:
        repaired.spans = recheck.spans
        repaired.issues = []
    else:
        repaired.spans = recheck.spans or grown
        repaired.issues = recheck.issues
    return repaired
