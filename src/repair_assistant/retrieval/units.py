"""Resolve retrieval representations back to their parent unit (ADR-0048).

A semantic unit is reachable through several representations — its overview, its
searchable facts, its representative questions — so one unit can match a query
several times. Those matches are the same piece of documentation, so they
collapse into one evidence hit whose text is the unit's authoritative
``source_text``.

This is the same move ``coalesce_problem_hits`` already makes for same-problem
table rows ([ADR-0042](../../docs/adr/0042-guide1-anchor-and-checklist-coalesce.md)):
formatting applied after ranking, not a ranking constant. The R11/R20/R22 freeze
is untouched — no score is recomputed here, the group simply keeps its best.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repair_assistant.retrieval.search import Hit


@dataclass(frozen=True)
class UnitRecord:
    """A semantic knowledge unit as retrieval needs it."""

    id: int
    unit_key: str
    title: str
    unit_type: str
    page_start: int | None
    page_end: int | None
    section_path: list[str] = field(default_factory=list)
    source_text: str = ""
    source_span: list[str] = field(default_factory=list)

    @property
    def page_label(self) -> str:
        if self.page_start is None:
            return ""
        if self.page_end is None or self.page_end == self.page_start:
            return f"p.{self.page_start}"
        return f"pp.{self.page_start}-{self.page_end}"


def load_units(db: Any, unit_ids: list[int]) -> dict[int, UnitRecord]:
    """Fetch every matched unit in one query."""
    wanted = sorted({int(i) for i in unit_ids if i is not None})
    if not wanted:
        return {}
    try:
        rows = db.fetchall(
            """
            SELECT id, unit_key, title, unit_type, page_start, page_end,
                   section_path, source_text, source_span
            FROM semantic_units
            WHERE id = ANY(%s::bigint[])
            """,
            (wanted,),
        )
    except Exception:
        # A failure here must not hide results: the representation text is a
        # worse answer than the unit, but it is still the right document.
        return {}
    out: dict[int, UnitRecord] = {}
    for row in rows or []:
        section_path = row[6] if isinstance(row[6], list) else []
        source_span = row[8] if isinstance(row[8], list) else []
        out[int(row[0])] = UnitRecord(
            id=int(row[0]),
            unit_key=str(row[1]),
            title=str(row[2] or ""),
            unit_type=str(row[3] or "other"),
            page_start=row[4],
            page_end=row[5],
            section_path=[str(p) for p in section_path],
            source_text=str(row[7] or ""),
            source_span=[str(a) for a in source_span],
        )
    return out


def collapse_semantic_units(db: Any, hits: list[Hit]) -> list[Hit]:
    """Group representation hits by parent unit and swap in the unit's text.

    Legacy hits pass through untouched, and a document with no semantic hits
    costs no query at all.
    """
    if not hits or not any(h.unit_id for h in hits):
        return hits

    units = load_units(db, [h.unit_id for h in hits if h.unit_id])
    if not units:
        return hits

    groups: dict[int, list[Hit]] = {}
    order: list[tuple[str, Any]] = []
    for hit in hits:
        unit_id = hit.unit_id
        if not unit_id or unit_id not in units:
            order.append(("one", hit))
            continue
        if unit_id not in groups:
            groups[unit_id] = []
            order.append(("unit", unit_id))
        groups[unit_id].append(hit)

    out: list[Hit] = []
    for kind, item in order:
        if kind == "one":
            out.append(item)
            continue
        out.append(_unit_hit(units[item], groups[item]))
    return out


def _unit_hit(unit: UnitRecord, matched: list[Hit]) -> Hit:
    """One evidence hit for a unit, carrying which representations matched."""
    best = max(matched, key=lambda h: float(h.score))
    meta = dict(best.metadata or {})
    meta.update(
        {
            "semantic_unit": True,
            "unit_key": unit.unit_key,
            "unit_title": unit.title,
            "unit_type": unit.unit_type,
            "page_start": unit.page_start,
            "page_end": unit.page_end,
            "page_label": unit.page_label,
            "section_path": list(unit.section_path),
            "source_span": list(unit.source_span),
            "matched_representations": [
                {
                    "rep_kind": h.rep_kind,
                    "chunk_id": h.chunk_id,
                    "score": round(float(h.score), 6),
                }
                for h in sorted(matched, key=lambda h: float(h.score), reverse=True)
            ],
        }
    )
    # A representation's bbox would highlight generated text on the page raster.
    meta.pop("bbox", None)

    codes: list[str] = []
    for hit in matched:
        codes.extend(hit.error_codes or [])

    return Hit(
        # The unit key is the citable identity: a reviewer and a technician both
        # need to land on the unit, not on whichever representation matched.
        doc_id=best.doc_id,
        chunk_id=unit.unit_key,
        text=unit.source_text or best.text,
        page=unit.page_start if unit.page_start is not None else best.page,
        kind="semantic_unit",
        error_codes=list(dict.fromkeys(codes)),
        publication_number=best.publication_number,
        revision=best.revision,
        score=float(best.score),
        apply_reason=best.apply_reason,
        metadata=meta,
        unit_id=unit.id,
        rep_kind=None,
        strategy=best.strategy,
    )


__all__ = ["UnitRecord", "collapse_semantic_units", "load_units"]
