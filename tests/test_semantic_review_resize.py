"""Resize-with-push / absorb for intentional boundary edits."""

from __future__ import annotations

from pathlib import Path

import pytest

from repair_assistant.semantic import review as review_mod
from repair_assistant.semantic.units import SemanticUnit
from tests.semantic_fixtures import patch_pdf_segmentation, write_stub_pdf


class _MemStore:
    """Stand-in for semantic_store unit CRUD used by review helpers."""

    def __init__(self) -> None:
        self.units: dict[str, SemanticUnit] = {}

    def list_units(self, _db, _version_id: int) -> list[SemanticUnit]:
        return sorted(self.units.values(), key=lambda u: (u.page_start or 0, u.start_y, u.ordinal))

    def update_unit(self, _db, _version_id: int, unit: SemanticUnit) -> None:
        self.units[unit.unit_key] = unit

    def delete_unit(self, _db, _version_id: int, unit_key: str) -> None:
        self.units.pop(unit_key, None)

    def insert_unit(self, _db, _version_id: int, unit: SemanticUnit) -> SemanticUnit:
        self.units[unit.unit_key] = unit
        return unit


def _unit(
    key: str,
    *,
    ordinal: int,
    start: int,
    end: int,
    start_y: float = 0.0,
    end_y: float = 1.0,
    title: str = "Unit",
) -> SemanticUnit:
    return SemanticUnit(
        unit_key=key,
        ordinal=ordinal,
        title=title,
        unit_type="overview",
        page_start=start,
        page_end=end,
        start_y=start_y,
        end_y=end_y,
        section_path=[],
        source_text="x",
        source_span=[f"p{start}@{start_y}", f"p{end}@{end_y}"],
        content_hash="h",
        review_status="proposed",
        origin="llm",
    )


@pytest.fixture
def pdf_and_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pdf = write_stub_pdf(tmp_path / "doc.pdf", pages=3)
    patch_pdf_segmentation(monkeypatch, pdf, pages=3)
    mem = _MemStore()
    monkeypatch.setattr(review_mod.semantic_store, "list_units", mem.list_units)
    monkeypatch.setattr(review_mod.semantic_store, "update_unit", mem.update_unit)
    monkeypatch.setattr(review_mod.semantic_store, "delete_unit", mem.delete_unit)
    monkeypatch.setattr(review_mod.semantic_store, "insert_unit", mem.insert_unit)
    return pdf, mem


def test_resize_pushes_next_neighbor(pdf_and_store) -> None:
    pdf, mem = pdf_and_store
    a = _unit("a", ordinal=0, start=1, end=1, start_y=0.0, end_y=0.4, title="A")
    b = _unit("b", ordinal=1, start=1, end=1, start_y=0.4, end_y=1.0, title="B")
    mem.units = {"a": a, "b": b}

    outcome = review_mod.resize_unit_pushing_neighbors(
        None,
        1,
        a,
        pdf_path=pdf,
        end_y=0.7,
    )

    assert "b" not in outcome.removed
    assert mem.units["a"].end_y == pytest.approx(0.7)
    assert mem.units["b"].start_y == pytest.approx(0.7)
    assert mem.units["b"].end_y == pytest.approx(1.0)


def test_resize_pushes_next_across_page_boundary(pdf_and_store) -> None:
    pdf, mem = pdf_and_store
    a = _unit("a", ordinal=0, start=1, end=1, start_y=0.0, end_y=1.0, title="A")
    b = _unit("b", ordinal=1, start=2, end=2, start_y=0.0, end_y=1.0, title="B")
    mem.units = {"a": a, "b": b}

    outcome = review_mod.resize_unit_pushing_neighbors(
        None,
        1,
        a,
        pdf_path=pdf,
        end_page=2,
        end_y=0.35,
    )

    assert "b" not in outcome.removed
    assert mem.units["a"].page_end == 2
    assert mem.units["a"].end_y == pytest.approx(0.35)
    assert mem.units["b"].page_start == 2
    assert mem.units["b"].start_y == pytest.approx(0.35)


def test_resize_absorbs_next_when_fully_covered(pdf_and_store) -> None:
    pdf, mem = pdf_and_store
    a = _unit("a", ordinal=0, start=1, end=1, start_y=0.0, end_y=0.4, title="A")
    b = _unit("b", ordinal=1, start=1, end=1, start_y=0.4, end_y=0.8, title="B")
    mem.units = {"a": a, "b": b}

    outcome = review_mod.resize_unit_pushing_neighbors(
        None,
        1,
        a,
        pdf_path=pdf,
        end_y=0.8,
    )

    assert outcome.removed == ["b"]
    assert "b" not in mem.units
    assert mem.units["a"].end_y == pytest.approx(0.8)
