"""Representation-to-unit resolution and the generation evidence budget.

Slice 3 of the semantic chunking work: retrieval finds a representation, but
generation must read the unit's own source text (ADR-0048 decision 1).
"""

from __future__ import annotations

from repair_assistant.qa.context import (
    evidence_text,
    format_evidence,
    format_label,
    unit_page_label,
)
from repair_assistant.retrieval.search import Hit
from repair_assistant.retrieval.units import collapse_semantic_units, load_units

UNIT_SOURCE = (
    "WARNING: Disconnect power before servicing the drain pump.\n\n"
    "TEST #7: Drain Pump. Perform this test when the washer will not drain.\n\n"
    "Step 1: measure the winding resistance at CN4; expect 1.4 to 1.9 ohms.\n\n"
    "If any reading is out of range, replace the drain pump and retest."
)

UNIT_ROW = (
    41,
    "001-test-7-drain-pump",
    "TEST #7: Drain Pump",
    "warning_with_procedure",
    34,
    36,
    ["DRAIN SYSTEM"],
    UNIT_SOURCE,
    ["p34-heading-drain", "p34-procedure-head", "p36-prose-result"],
)


class FakeDb:
    """Records the queries retrieval makes so single-query loading is testable."""

    def __init__(self, rows: list[tuple] | None = None, *, fail: bool = False) -> None:
        self.rows = rows if rows is not None else [UNIT_ROW]
        self.fail = fail
        self.queries: list[tuple] = []

    def fetchall(self, sql: str, params: tuple | None = None) -> list[tuple]:
        self.queries.append((sql, params))
        if self.fail:
            raise RuntimeError("database is unreachable")
        wanted = set(params[0]) if params else set()
        return [r for r in self.rows if r[0] in wanted]


def _rep_hit(rep_kind: str, score: float, *, unit_id: int = 41) -> Hit:
    return Hit(
        doc_id="ci-semantic-doc",
        chunk_id=f"u-001-test-7-drain-pump-{rep_kind}",
        text=f"generated {rep_kind} text that must not reach the model",
        page=34,
        kind="semantic_rep",
        error_codes=["F9E2"] if rep_kind == "facts" else [],
        publication_number="SYNTH-CI-SEM",
        revision="A",
        score=score,
        metadata={"rep_kind": rep_kind, "unit_key": "001-test-7-drain-pump"},
        unit_id=unit_id,
        rep_kind=rep_kind,
        strategy="semantic_llm",
    )


def _legacy_hit(chunk_id: str = "p8-table_row-a", score: float = 0.5) -> Hit:
    return Hit(
        doc_id="ci-legacy-doc",
        chunk_id=chunk_id,
        text="F5E2 | Door lock fault | Check the lock assembly.",
        page=8,
        kind="table_row",
        error_codes=["F5E2"],
        publication_number="W11320651",
        revision="A",
        score=score,
        metadata={"bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4}},
        strategy="structured",
    )


# --- unit loading ----------------------------------------------------------


def test_units_load_in_one_query() -> None:
    db = FakeDb([UNIT_ROW, (42, "002-codes", "Codes", "troubleshooting_table", 37, 37, [], "F9E1 row", [])])
    units = load_units(db, [41, 42, 41, None])

    assert len(db.queries) == 1, "one query for every matched unit"
    assert db.queries[0][1] == ([41, 42],), "deduplicated and sorted"
    assert units[41].unit_key == "001-test-7-drain-pump"
    assert units[41].page_label == "pp.34-36"
    assert units[42].page_label == "p.37"


def test_no_semantic_hits_costs_no_query() -> None:
    db = FakeDb()
    hits = [_legacy_hit(), _legacy_hit("p8-table_row-b")]
    assert collapse_semantic_units(db, hits) == hits
    assert db.queries == []


def test_a_database_failure_leaves_the_representation_hits_alone() -> None:
    db = FakeDb(fail=True)
    hits = [_rep_hit("overview", 0.9)]
    assert collapse_semantic_units(db, hits) == hits


# --- resolution ------------------------------------------------------------


def test_a_representation_hit_resolves_to_its_parent_unit() -> None:
    db = FakeDb()
    collapsed = collapse_semantic_units(db, [_rep_hit("questions", 0.81)])

    assert len(collapsed) == 1
    unit = collapsed[0]
    assert unit.text == UNIT_SOURCE, "generation reads the unit, not the representation"
    assert "generated questions text" not in unit.text
    assert unit.chunk_id == "001-test-7-drain-pump", "the unit key is the citable id"
    assert unit.kind == "semantic_unit"
    assert unit.is_semantic_unit
    assert unit.rep_kind is None
    assert unit.strategy == "semantic_llm"
    assert unit.page == 34
    assert unit.metadata["page_label"] == "pp.34-36"
    assert unit.metadata["unit_title"] == "TEST #7: Drain Pump"
    assert unit.metadata["source_span"][0] == "p34-heading-drain"


def test_several_representations_of_one_unit_collapse_to_one_hit() -> None:
    db = FakeDb()
    hits = [
        _rep_hit("overview", 0.92),
        _rep_hit("questions", 0.88),
        _rep_hit("facts", 0.71),
    ]
    collapsed = collapse_semantic_units(db, hits)

    assert len(collapsed) == 1, "deduplicated by unit_id"
    unit = collapsed[0]
    assert unit.score == 0.92, "the group keeps its best score, nothing is recomputed"
    matched = unit.metadata["matched_representations"]
    assert [m["rep_kind"] for m in matched] == ["overview", "questions", "facts"]
    assert matched[0]["score"] == 0.92
    assert unit.error_codes == ["F9E2"], "codes from every matched representation"


def test_legacy_hits_pass_through_and_keep_their_position() -> None:
    db = FakeDb()
    hits = [
        _legacy_hit("p8-table_row-a", 0.95),
        _rep_hit("overview", 0.90),
        _legacy_hit("p8-table_row-b", 0.60),
        _rep_hit("facts", 0.55),
    ]
    collapsed = collapse_semantic_units(db, hits)

    assert [h.chunk_id for h in collapsed] == [
        "p8-table_row-a",
        "001-test-7-drain-pump",
        "p8-table_row-b",
    ]
    assert [round(h.score, 2) for h in collapsed] == [0.95, 0.90, 0.60]
    legacy = collapsed[0]
    assert legacy.text.startswith("F5E2 |"), "non-selected documents are unchanged"
    assert legacy.metadata["bbox"] == {"x0": 1, "y0": 2, "x1": 3, "y1": 4}


def test_two_units_stay_separate() -> None:
    second = (42, "002-codes", "Drain codes", "troubleshooting_table", 37, 38, [], "F9E1 | Long drain", [])
    db = FakeDb([UNIT_ROW, second])
    collapsed = collapse_semantic_units(
        db, [_rep_hit("overview", 0.9), _rep_hit("facts", 0.8, unit_id=42)]
    )
    assert [h.chunk_id for h in collapsed] == ["001-test-7-drain-pump", "002-codes"]


def test_a_unit_hit_drops_the_representation_bbox() -> None:
    """A representation's bbox would highlight generated text on the raster."""
    db = FakeDb()
    hit = _rep_hit("overview", 0.9)
    hit.metadata = {**hit.metadata, "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4}}
    collapsed = collapse_semantic_units(db, [hit])
    assert "bbox" not in collapsed[0].metadata


def test_an_unknown_unit_id_does_not_drop_the_hit() -> None:
    db = FakeDb([UNIT_ROW])
    collapsed = collapse_semantic_units(
        db, [_rep_hit("overview", 0.9), _rep_hit("facts", 0.8, unit_id=999)]
    )
    assert len(collapsed) == 2
    assert collapsed[1].chunk_id.endswith("-facts"), "unresolved hit kept as-is"


# --- generation ------------------------------------------------------------


def _unit_hit(text: str = UNIT_SOURCE, score: float = 0.9) -> Hit:
    return collapse_semantic_units(
        FakeDb([(*UNIT_ROW[:7], text, UNIT_ROW[8])]), [_rep_hit("overview", score)]
    )[0]


def test_unit_page_label_uses_the_range() -> None:
    assert unit_page_label(_unit_hit()) == "pp.34-36"
    assert unit_page_label(_legacy_hit()) == ""


def test_citation_label_carries_the_page_range_and_unit_title() -> None:
    label = format_label(_unit_hit())
    assert "SYNTH-CI-SEM Rev A pp.34-36 [semantic]" in label
    assert "TEST #7: Drain Pump" in label
    assert " p.34" not in label, "a multi-page unit is not cited as one page"


def test_legacy_labels_are_unchanged() -> None:
    assert format_label(_legacy_hit()) == "W11320651 Rev A p.8 [structured] — F5E2"


def test_a_unit_is_never_excerpt_truncated() -> None:
    long_unit = _unit_hit("PROCEDURE. " + ("step detail. " * 900))
    text = evidence_text(long_unit)

    assert len(text) > 2000, "the 2000-char excerpt cap does not apply to a unit"
    assert text == long_unit.text.strip()
    assert not text.endswith("...")


def test_a_legacy_chunk_sends_full_text() -> None:
    legacy = _legacy_hit()
    legacy.text = "filler. " * 600 + "status led blinks twice. " + "filler. " * 600
    text = evidence_text(legacy, query="what does the status led mean")
    assert text == legacy.text.strip()
    assert len(text) > 2000


def test_generation_receives_source_text_not_the_representation() -> None:
    body, citations = format_evidence([_unit_hit()], query="washer will not drain")

    assert "WARNING: Disconnect power" in body
    assert "TEST #7: Drain Pump" in body
    assert "1.4 to 1.9 ohms" in body
    assert "generated overview text" not in body
    assert citations[0].chunk_id == "001-test-7-drain-pump", "unit_key citation"
    assert citations[0].block_text == UNIT_SOURCE


def test_an_oversize_unit_drops_the_lowest_ranked_evidence_not_its_own_tail() -> None:
    big = _unit_hit("PROCEDURE START. " + ("step detail. " * 700) + " PROCEDURE END.", 0.95)
    small = _legacy_hit("p8-table_row-a", 0.40)
    body, citations = format_evidence([big, small], max_chars=9_000)

    assert len(citations) == 1, "the lowest-ranked block was dropped whole"
    assert citations[0].index == 1
    assert "PROCEDURE START" in body
    assert "PROCEDURE END" in body, "the unit kept its tail"
    assert "F5E2 |" not in body


def test_smaller_evidence_after_an_oversize_unit_still_fits() -> None:
    big = _unit_hit("PROCEDURE. " + ("step detail. " * 400), 0.95)
    huge = _unit_hit("SECOND UNIT. " + ("more detail. " * 800), 0.80)
    small = _legacy_hit("p8-table_row-a", 0.40)
    body, citations = format_evidence([big, huge, small], max_chars=6_000)

    labels = [c.label for c in citations]
    assert len(citations) == 2, "the unit that did not fit was skipped, not the tail"
    assert "SECOND UNIT" not in body
    assert "F5E2 |" in body
    assert [c.index for c in citations] == [1, 2], "indices stay contiguous"
    assert all(labels)


def test_the_top_hit_is_included_even_when_it_alone_exceeds_the_budget() -> None:
    """Answering from nothing is worse than one oversize block."""
    big = _unit_hit("PROCEDURE. " + ("step detail. " * 900), 0.95)
    body, citations = format_evidence([big, _legacy_hit()], max_chars=1_000)

    assert len(citations) == 1
    assert citations[0].block_text == big.text.strip()
    assert "step detail." in body


def test_evidence_blocks_stay_aligned_with_citations_after_a_drop() -> None:
    from repair_assistant.qa.context import evidence_blocks_from_citations

    big = _unit_hit("PROCEDURE. " + ("step detail. " * 500), 0.95)
    small = _legacy_hit("p8-table_row-a", 0.40)
    _, citations = format_evidence([big, small], max_chars=5_000)
    blocks = evidence_blocks_from_citations(citations)

    assert set(blocks) == {c.index for c in citations}
    assert blocks[1].startswith("PROCEDURE.")
