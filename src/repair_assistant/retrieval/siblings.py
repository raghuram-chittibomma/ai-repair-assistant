"""Pull remaining cause rows for the same troubleshooting problem.

Search often returns the last (TEST #N) or mid-table row. The literature
lists first remedies above that. Expand from ``problem_title`` + page —
not a new ranking constant.
"""

from __future__ import annotations

import re
from typing import Any

from repair_assistant.retrieval.search import Hit

_TEST_PTR = re.compile(r"see test\s*#", re.I)
_FIRST_REMEDY = re.compile(
    r"reset washer|unplug and reconnect|ensure that door is completely closed",
    re.I,
)

_SIBLING_SQL = """
SELECT doc_id, chunk_id, text, page, kind, error_codes,
       publication_number, revision, metadata
FROM active_chunks
WHERE doc_id = %s AND page = %s AND kind = 'table_row'
  AND metadata->>'problem_title' = %s
"""


def _y0(hit: Hit) -> float:
    raw = (hit.metadata or {}).get("bbox")
    if not isinstance(raw, dict):
        return 1e9
    try:
        return float(raw["y0"])
    except (KeyError, TypeError, ValueError):
        return 1e9


def sibling_sort_key(hit: Hit) -> tuple[int, int, float]:
    """On-page first remedies, then other causes, then See TEST #N."""
    text = hit.text or ""
    test = 1 if _TEST_PTR.search(text) else 0
    first = 0 if _FIRST_REMEDY.search(text) else 1
    return (test, first, _y0(hit))


def _row_to_hit(row: tuple, *, score: float) -> Hit:
    meta = row[8] if len(row) > 8 and isinstance(row[8], dict) else {}
    return Hit(
        doc_id=str(row[0]),
        chunk_id=str(row[1]),
        text=str(row[2] or ""),
        page=row[3],
        kind=row[4],
        error_codes=list(row[5] or []),
        publication_number=row[6],
        revision=row[7],
        score=score,
        metadata=meta,
    )


def expand_problem_siblings(
    db: Any,
    hits: list[Hit],
    *,
    max_extra: int = 8,
) -> list[Hit]:
    """Insert same-problem, same-page rows; keep first remedies first."""
    if not hits:
        return hits
    seen = {(h.doc_id, h.chunk_id) for h in hits}
    by_problem: dict[tuple[str, int, str], list[Hit]] = {}
    try:
        for hit in hits:
            problem = str((hit.metadata or {}).get("problem_title") or "").strip()
            if not problem or hit.page is None:
                continue
            key = (hit.doc_id, int(hit.page), problem)
            if key in by_problem:
                continue
            rows = db.fetchall(_SIBLING_SQL, (hit.doc_id, hit.page, problem))
            by_problem[key] = [
                _row_to_hit(row, score=float(hit.score))
                for row in rows or []
            ]
    except Exception:
        return hits

    extras: list[Hit] = []
    for group in by_problem.values():
        for sib in sorted(group, key=sibling_sort_key):
            key = (sib.doc_id, sib.chunk_id)
            if key in seen:
                continue
            extras.append(sib)
            seen.add(key)
            if len(extras) >= max_extra:
                break
        if len(extras) >= max_extra:
            break

    if extras:
        hits = _rebuild_with_siblings(hits, by_problem)
    return coalesce_problem_hits(hits)


def _rebuild_with_siblings(
    hits: list[Hit],
    by_problem: dict[tuple[str, int, str], list[Hit]],
) -> list[Hit]:
    # Rebuild: for each original hit, emit ordered siblings of its problem
    # once, then the remaining originals that were not siblings.
    emitted: set[tuple[str, str]] = set()
    out: list[Hit] = []
    groups_done: set[tuple[str, int, str]] = set()

    def _emit(hit: Hit) -> None:
        key = (hit.doc_id, hit.chunk_id)
        if key in emitted:
            return
        emitted.add(key)
        out.append(hit)

    for hit in hits:
        problem = str((hit.metadata or {}).get("problem_title") or "").strip()
        if problem and hit.page is not None:
            gkey = (hit.doc_id, int(hit.page), problem)
            if gkey not in groups_done:
                groups_done.add(gkey)
                for sib in sorted(by_problem.get(gkey, [hit]), key=sibling_sort_key):
                    _emit(sib)
                continue
        _emit(hit)
    return out


def _union_bbox(hits: list[Hit]) -> dict | None:
    boxes: list[dict] = []
    for hit in hits:
        raw = (hit.metadata or {}).get("bbox")
        if isinstance(raw, dict) and {"x0", "y0", "x1", "y1"} <= raw.keys():
            boxes.append(raw)
    if not boxes:
        return None
    return {
        "x0": min(float(b["x0"]) for b in boxes),
        "y0": min(float(b["y0"]) for b in boxes),
        "x1": max(float(b["x1"]) for b in boxes),
        "y1": max(float(b["y1"]) for b in boxes),
    }


def _pair_line(hit: Hit) -> str:
    body = str((hit.metadata or {}).get("body_text") or hit.text or "")
    cause = re.search(r"Possible cause:\s*([^|]+)", body, re.I)
    checks = re.search(r"Checks(?:\s*&\s*tests)?:\s*(.+)$", body, re.I | re.S)
    if cause and checks:
        return (
            f"Possible cause: {cause.group(1).strip()} | "
            f"Checks & tests: {checks.group(1).strip()}"
        )
    return " ".join(body.split())


def coalesce_problem_hits(hits: list[Hit]) -> list[Hit]:
    """One evidence hit per problem on a page so [n] is the full checklist."""
    if len(hits) < 2:
        return hits
    groups: dict[tuple[str, int, str], list[Hit]] = {}
    order: list[tuple[str, object]] = []
    for hit in hits:
        problem = str((hit.metadata or {}).get("problem_title") or "").strip()
        if not problem or hit.page is None:
            order.append(("one", hit))
            continue
        key = (hit.doc_id, int(hit.page), problem.casefold())
        if key not in groups:
            groups[key] = []
            order.append(("grp", key))
        groups[key].append(hit)

    out: list[Hit] = []
    for kind, item in order:
        if kind == "one":
            assert isinstance(item, Hit)
            out.append(item)
            continue
        group = sorted(groups[item], key=sibling_sort_key)
        first = group[0]
        if len(group) == 1:
            out.append(first)
            continue
        problem = str((first.metadata or {}).get("problem_title") or "").strip()
        lines = [f"Problem: {problem}"]
        lines.extend(_pair_line(h) for h in group)
        meta = dict(first.metadata or {})
        meta["body_text"] = "\n".join(lines)
        for hit in group:
            src = hit.metadata or {}
            for key in ("page_width", "page_height", "bbox_space"):
                if meta.get(key) is None and src.get(key) is not None:
                    meta[key] = src[key]
        box = _union_bbox(group)
        if box:
            meta["bbox"] = box
        meta["coalesced_chunk_ids"] = [h.chunk_id for h in group]
        codes: list[str] = []
        for hit in group:
            codes.extend(hit.error_codes or [])
        out.append(
            Hit(
                doc_id=first.doc_id,
                chunk_id=first.chunk_id,
                text="\n".join(lines),
                page=first.page,
                kind=first.kind,
                error_codes=list(dict.fromkeys(codes)),
                publication_number=first.publication_number,
                revision=first.revision,
                score=max(float(h.score) for h in group),
                apply_reason=first.apply_reason,
                metadata=meta,
                unit_id=first.unit_id,
                rep_kind=first.rep_kind,
                strategy=first.strategy,
            )
        )
    return out


__all__ = [
    "coalesce_problem_hits",
    "expand_problem_siblings",
    "sibling_sort_key",
]
