"""Same-problem row expand keeps first remedies ahead of TEST # pointers."""

from __future__ import annotations

from repair_assistant.retrieval.search import Hit
from repair_assistant.retrieval.siblings import (
    coalesce_problem_hits,
    expand_problem_siblings,
    sibling_sort_key,
)


def _hit(
    chunk_id: str,
    text: str,
    *,
    problem: str = "DOOR WON'T UNLOCK",
    y0: float | None = None,
    score: float = 0.5,
) -> Hit:
    meta: dict = {"problem_title": problem}
    if y0 is not None:
        meta["bbox"] = {"x0": 0, "y0": y0, "x1": 10, "y1": y0 + 10}
    return Hit(
        doc_id="tech-sheet-w11320651",
        chunk_id=chunk_id,
        text=text,
        page=10,
        kind="table_row",
        error_codes=[],
        publication_number="W11320651",
        revision="B",
        score=score,
        metadata=meta,
    )


class _FakeDb:
    def __init__(self, rows: list[Hit]) -> None:
        self.rows = rows

    def fetchall(self, sql: str, params: tuple) -> list[tuple]:
        del sql
        doc_id, page, problem = params
        out = []
        for hit in self.rows:
            if (
                hit.doc_id == doc_id
                and hit.page == page
                and (hit.metadata or {}).get("problem_title") == problem
            ):
                out.append(
                    (
                        hit.doc_id,
                        hit.chunk_id,
                        hit.text,
                        hit.page,
                        hit.kind,
                        hit.error_codes,
                        hit.publication_number,
                        hit.revision,
                        hit.metadata,
                    )
                )
        return out


def test_sibling_sort_puts_reset_before_test() -> None:
    reset = _hit("a", "Problem: DOOR WON'T UNLOCK | Reset washer. Unplug and reconnect.")
    test = _hit("b", "Problem: DOOR WON'T UNLOCK | See TEST #4: Door Lock System.")
    assert sibling_sort_key(reset) < sibling_sort_key(test)


def test_expand_inserts_reset_washer_first() -> None:
    latch = _hit(
        "latch",
        "Problem: DOOR WON'T UNLOCK | Check door lock mechanism and repair.",
        y0=280,
        score=0.9,
    )
    reset = _hit(
        "reset",
        "Problem: DOOR WON'T UNLOCK | Reset washer. Unplug and reconnect the power cord.",
        score=0.2,
    )
    test = _hit(
        "test4",
        "Problem: DOOR WON'T UNLOCK | See TEST #4: Door Lock System, page 15.",
        score=0.8,
    )
    db = _FakeDb([latch, reset, test])
    ordered = expand_problem_siblings(db, [latch])
    assert len(ordered) == 1
    text = ordered[0].text.lower()
    assert "reset washer" in text
    assert "test #4" in text
    assert "repair" in text
    assert ordered[0].metadata.get("coalesced_chunk_ids") == ["reset", "latch", "test4"]


def test_coalesce_one_citation_lists_every_cause() -> None:
    reset = _hit("reset", "Possible cause: Reset washer. | Checks & tests: Unplug.")
    latch = _hit("latch", "Possible cause: Misaligned latch. | Checks & tests: Repair.")
    merged = coalesce_problem_hits([reset, latch])
    assert len(merged) == 1
    assert "Reset washer" in merged[0].text
    assert "Misaligned" in merged[0].text


def test_coalesce_keeps_sibling_page_layout() -> None:
    """Reset row often has no box; latch does. Overlay still needs page size."""
    from repair_assistant.qa.context import layout_from_hit

    reset = _hit("reset", "Possible cause: Reset washer. | Checks & tests: Unplug.")
    latch = _hit(
        "latch",
        "Possible cause: Misaligned latch. | Checks & tests: Repair.",
        y0=280,
    )
    latch.metadata["page_width"] = 396.0
    latch.metadata["page_height"] = 612.0
    latch.metadata["bbox_space"] = "pdfplumber_pt"
    merged = coalesce_problem_hits([reset, latch])
    box, width, height = layout_from_hit(merged[0])
    assert box is not None
    assert width == 396.0
    assert height == 612.0
    assert box["y0"] == 280.0


def test_expand_noop_without_problem_title() -> None:
    lone = Hit(
        doc_id="use-and-care",
        chunk_id="u1",
        text="Door will not unlock. Touch START/PAUSE.",
        page=26,
        kind="table_row",
        error_codes=[],
        publication_number="W11156985",
        revision="A",
        score=0.9,
        metadata={},
    )
    assert expand_problem_siblings(_FakeDb([]), [lone]) == [lone]
