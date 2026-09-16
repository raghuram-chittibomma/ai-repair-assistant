"""The curator step end to end against a real pgvector (ADR-0049).

Skipped unless REPAIR_TEST_DATABASE_URL is set.
"""

from __future__ import annotations

import json

import pytest

from repair_assistant.semantic import store as semantic_store
from repair_assistant.semantic.curate import (
    STATUS_PROPOSED,
    STATUS_REJECTED,
    propose_semantic_version,
    regenerate_unit_representations,
)
from repair_assistant.semantic.lifecycle import (
    STATUS_CANDIDATE,
    STRATEGY_SEMANTIC,
    STRATEGY_STRUCTURED,
    LifecycleError,
    activate,
    active_version,
    mark_ready,
)
from repair_assistant.semantic.units import REVIEW_APPROVED, resegment_unit
from tests.postgres_support import FixedEmbedder, make_chunk, upsert_structured
from tests.semantic_fixtures import (
    GOOD_UNITS,
    FakeRepresenter,
    FakeSegmenter,
    patch_pdf_segmentation,
    write_stub_pdf,
)

pytestmark = pytest.mark.postgres

DOC_ID = "ci-semantic-doc"


@pytest.fixture
def pdf_env(monkeypatch, tmp_path):
    pdf = write_stub_pdf(tmp_path / "documents" / f"{DOC_ID}.pdf")
    patch_pdf_segmentation(monkeypatch, pdf, pages=3)
    return pdf


def _legacy(db, embedder: FixedEmbedder | None = None):
    return upsert_structured(
        db,
        DOC_ID,
        [
            make_chunk(
                doc_id=DOC_ID,
                chunk_id="p1-prose-legacy",
                text="Legacy chunk about the drain pump.",
                publication_number="SYNTH-CI-SEM",
            )
        ],
        embedder,
    )


def _propose(
    db,
    pdf_env,
    *,
    units=None,
    representer=None,
    embedder=None,
    repair_gaps=False,
    generate_representations=True,
):
    return propose_semantic_version(
        db,
        doc_id=DOC_ID,
        pdf_path=pdf_env,
        segmenter=FakeSegmenter({"units": units if units is not None else GOOD_UNITS}),
        representer=representer or FakeRepresenter(),
        embedder=embedder or FixedEmbedder(),
        doc_title="CI Service Manual",
        publication_number="SYNTH-CI-SEM",
        revision="A",
        repair_gaps=repair_gaps,
        generate_representations=generate_representations,
    )


def test_proposal_creates_a_candidate_and_leaves_legacy_active(pg_db, pdf_env) -> None:
    legacy = _legacy(pg_db)
    result = _propose(pg_db, pdf_env)

    assert result.status == STATUS_PROPOSED, result.detail
    assert result.version.strategy == STRATEGY_SEMANTIC
    assert result.version.status == STATUS_CANDIDATE
    assert len(result.units) == 2
    assert result.indexed == 6
    assert result.embedded == 6

    still_legacy = active_version(pg_db, DOC_ID)
    assert still_legacy.id == legacy.id
    assert still_legacy.strategy == STRATEGY_STRUCTURED
    visible = pg_db.fetchall(
        "SELECT chunk_id FROM active_chunks WHERE doc_id = %s", (DOC_ID,)
    )
    assert [r[0] for r in visible] == ["p1-prose-legacy"]


def test_several_reps_point_at_one_parent_unit(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    procedure = result.units[0]

    rows = pg_db.fetchall(
        """
        SELECT chunk_id, rep_kind, unit_id, kind, metadata
        FROM chunks
        WHERE doc_id = %s AND unit_id = %s ORDER BY rep_kind
        """,
        (DOC_ID, procedure.id),
    )
    assert [r[1] for r in rows] == ["facts", "overview", "questions"]
    assert {r[2] for r in rows} == {procedure.id}
    assert {r[3] for r in rows} == {"semantic_rep"}


def test_unit_source_text_is_thin_pdf_extract(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    procedure = semantic_store.list_units(pg_db, result.version.id)[0]
    assert "WARNING: Disconnect power" in procedure.source_text
    assert procedure.page_start == 1 and procedure.page_end == 2
    assert procedure.source_span[0].startswith("p1@")


def test_mixed_corpus_structured_and_semantic_both_in_active_chunks(
    pg_db, pdf_env
) -> None:
    """ADR-0047: one active version per doc; corpus may mix strategies."""
    other = "ci-structured-only"
    upsert_structured(
        pg_db,
        other,
        [
            make_chunk(
                doc_id=other,
                chunk_id="p1-prose-other",
                text="Another structured document.",
                publication_number="SYNTH-OTHER",
            )
        ],
        FixedEmbedder(),
    )
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    for unit in result.units:
        unit.review_status = REVIEW_APPROVED
        semantic_store.update_unit(pg_db, result.version.id, unit)
    mark_ready(pg_db, result.version.id)
    activate(pg_db, result.version.id)

    strategies = {
        r[0]
        for r in pg_db.fetchall(
            "SELECT DISTINCT strategy FROM active_chunks WHERE doc_id = ANY(%s)",
            ([DOC_ID, other],),
        )
    }
    assert STRATEGY_STRUCTURED in strategies
    assert STRATEGY_SEMANTIC in strategies


def test_a_gap_rejects_the_proposal_and_leaves_legacy_serving(pg_db, pdf_env) -> None:
    legacy = _legacy(pg_db)
    result = _propose(pg_db, pdf_env, units=[GOOD_UNITS[0]])

    assert result.status == STATUS_REJECTED
    assert "coverage_gap" in result.detail
    assert active_version(pg_db, DOC_ID).id == legacy.id


def test_repair_gaps_covers_missing_pages(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    partial = [
        dict(GOOD_UNITS[0]),
        {
            "start_page": 3,
            "end_page": 3,
            "start_y": 0.0,
            "end_y": 1.0,
            "title": "Codes",
            "unit_type": "troubleshooting_table",
            "rationale": "",
            "review_flag": "none",
            "review_note": "",
        },
    ]
    # Gap page 2 between unit1 end page2 and ... wait GOOD_UNITS[0] is 1-2, second is 3
    # That's full coverage. Use unit covering only page 1 and page 3.
    partial = [
        {
            "start_page": 1,
            "end_page": 1,
            "start_y": 0.0,
            "end_y": 1.0,
            "title": "A",
            "unit_type": "other",
            "rationale": "",
            "review_flag": "none",
            "review_note": "",
        },
        {
            "start_page": 3,
            "end_page": 3,
            "start_y": 0.0,
            "end_y": 1.0,
            "title": "C",
            "unit_type": "other",
            "rationale": "",
            "review_flag": "none",
            "review_note": "",
        },
    ]
    result = _propose(pg_db, pdf_env, units=partial, repair_gaps=True)
    assert result.status == STATUS_PROPOSED, result.detail
    assert result.report.repairs


def test_a_second_proposal_is_refused_while_one_is_open(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    _propose(pg_db, pdf_env)
    with pytest.raises(LifecycleError) as excinfo:
        _propose(pg_db, pdf_env)
    assert "already an open candidate" in str(excinfo.value)


def test_missing_pdf_is_rejected_without_a_version(pg_db, tmp_path) -> None:
    from pathlib import Path

    _legacy(pg_db)
    missing = Path(tmp_path) / "nope.pdf"
    result = propose_semantic_version(
        pg_db,
        doc_id=DOC_ID,
        pdf_path=missing,
        segmenter=FakeSegmenter({"units": GOOD_UNITS}),
        representer=FakeRepresenter(),
        embedder=FixedEmbedder(),
    )
    assert result.status == STATUS_REJECTED
    assert result.version is None
    assert "PDF not found" in result.detail


def test_regenerating_identical_text_keeps_the_existing_vector(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    unit = result.units[0]

    class CountingEmbedder(FixedEmbedder):
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)

    counter = CountingEmbedder()
    regenerate_unit_representations(
        pg_db,
        doc_id=DOC_ID,
        version_id=result.version.id,
        unit=unit,
        representer=FakeRepresenter(),
        embedder=counter,
        publication_number="SYNTH-CI-SEM",
        revision="A",
    )
    pg_db.commit()
    assert counter.calls == 0


def test_boundary_edit_rebuilds_source_from_pdf(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    edited = result.units[0]
    moved = resegment_unit(
        edited,
        pdf_path=pdf_env,
        start_page=1,
        end_page=1,
        title="TEST #7 only",
    )
    moved.id = edited.id
    semantic_store.update_unit(pg_db, result.version.id, moved)
    stored = semantic_store.get_unit(pg_db, result.version.id, moved.unit_key)
    assert stored.page_end == 1
    assert "F9E1" not in stored.source_text or "Step 2" not in stored.source_text


def test_proposal_records_modality_for_training(pg_db, pdf_env) -> None:
    _legacy(pg_db)
    result = _propose(pg_db, pdf_env)
    export = semantic_store.training_export(pg_db, result.version.id)
    assert export["proposals"][0]["llm_input"]["modality"] == "native_pdf"
    assert json.loads(export["proposals"][0]["raw_output"])["units"]
