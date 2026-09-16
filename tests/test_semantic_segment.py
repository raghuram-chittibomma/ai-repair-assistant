"""PDF page-range segmentation parsing and validation (ADR-0049)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repair_assistant.semantic.segment import (
    MODALITY_NATIVE_PDF,
    MODALITY_VISION,
    SegmentationError,
    choose_modality,
    parse_proposal,
    propose_boundaries,
)
from repair_assistant.semantic.units import content_hash, marker_span_ids, units_from_spans
from repair_assistant.semantic.validate import (
    COVERAGE_GAP,
    OVERLAPPING_UNITS,
    REVERSED_BOUNDARY,
    UNKNOWN_PAGE,
    absorb_gaps,
    validate,
)


class FakeSegmenter:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, *, images=None, pdf_path=None) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "images": images,
                "pdf_path": str(pdf_path) if pdf_path else None,
            }
        )
        return json.dumps(self.payload)


def _unit(start: int, end: int, title: str = "Unit", **extra) -> dict:
    return {
        "start_page": start,
        "end_page": end,
        "start_y": 0.0,
        "end_y": 1.0,
        "title": title,
        "unit_type": "other",
        "rationale": "test",
        "review_flag": "none",
        "review_note": "",
        **extra,
    }


def test_parse_proposal_reads_page_markers() -> None:
    units = parse_proposal(json.dumps({"units": [_unit(1, 2, "Drain")]}))
    assert units[0].start_page == 1
    assert units[0].end_page == 2
    assert units[0].title == "Drain"


def test_parse_proposal_rejects_empty() -> None:
    with pytest.raises(SegmentationError):
        parse_proposal("{}")


def test_validate_accepts_full_window_coverage() -> None:
    proposed = parse_proposal(
        json.dumps({"units": [_unit(1, 1, "A"), _unit(2, 3, "B")]})
    )
    report = validate(proposed, window_start=1, window_end=3)
    assert report.ok
    assert len(report.spans) == 2


def test_validate_rejects_overlap_and_gap() -> None:
    overlap = parse_proposal(
        json.dumps({"units": [_unit(1, 2), _unit(2, 3)]})
    )
    # page 2 in both — overlap when y ranges conflict; whole-page units overlap
    report = validate(overlap, window_start=1, window_end=3)
    assert OVERLAPPING_UNITS in report.codes() or COVERAGE_GAP in report.codes() or report.ok is False

    gap = parse_proposal(json.dumps({"units": [_unit(1, 1), _unit(3, 3)]}))
    report = validate(gap, window_start=1, window_end=3)
    assert COVERAGE_GAP in report.codes()


def test_validate_rejects_outside_window() -> None:
    proposed = parse_proposal(json.dumps({"units": [_unit(1, 5)]}))
    report = validate(proposed, window_start=1, window_end=3)
    assert UNKNOWN_PAGE in report.codes()


def test_validate_rejects_reversed() -> None:
    proposed = parse_proposal(json.dumps({"units": [_unit(3, 1)]}))
    report = validate(proposed, window_start=1, window_end=3)
    assert REVERSED_BOUNDARY in report.codes()


def test_absorb_gaps_extends_neighbours() -> None:
    proposed = parse_proposal(json.dumps({"units": [_unit(1, 1), _unit(3, 3)]}))
    report = validate(proposed, window_start=1, window_end=3)
    assert not report.ok
    repaired = absorb_gaps(report, window_start=1, window_end=3)
    assert repaired.ok or COVERAGE_GAP not in repaired.codes()
    assert repaired.repairs


def test_marker_span_ids_and_hash() -> None:
    ids = marker_span_ids(1, 4, start_y=0.0, end_y=1.0)
    assert ids[0].startswith("p1@")
    assert content_hash("hello", ids) != content_hash("hello!", ids)


def test_choose_modality_respects_force_flags(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    # Minimal valid-enough file for inspect may fail; force flags short-circuit.
    pdf.write_bytes(b"%PDF-1.4\n")
    assert choose_modality(pdf, force_vision=True) == MODALITY_VISION
    assert choose_modality(pdf, force_native=True) == MODALITY_NATIVE_PDF


def test_propose_boundaries_native_calls_with_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repair_assistant.semantic.segment as seg

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def fake_page_count(_path):
        return 2

    def fake_outline(_path, *, max_pages_per_part=40):
        from repair_assistant.semantic.pdf_extract import PdfOutlinePart

        return [PdfOutlinePart("All", 1, 2)]

    def fake_write(pdf_path, *, start_page, end_page, dest):
        dest.write_bytes(b"%PDF-1.4 part")
        return dest

    monkeypatch.setattr(seg, "page_count", fake_page_count)
    monkeypatch.setattr(seg, "outline_parts", fake_outline)
    monkeypatch.setattr(seg, "write_pdf_part", fake_write)
    monkeypatch.setattr(seg, "choose_modality", lambda *a, **k: MODALITY_NATIVE_PDF)

    llm = FakeSegmenter({"units": [_unit(1, 2, "Whole")]})
    proposal = propose_boundaries(pdf, llm=llm, doc_id="doc", force_native=True)
    assert proposal.modality == MODALITY_NATIVE_PDF
    assert llm.calls and llm.calls[0]["pdf_path"]
    assert proposal.units[0].title == "Whole"


def test_propose_boundaries_vision_sends_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repair_assistant.semantic.segment as seg

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def fake_page_count(_path):
        return 1

    def fake_outline(_path, *, max_pages_per_part=40):
        from repair_assistant.semantic.pdf_extract import PdfOutlinePart

        return [PdfOutlinePart("Scan", 1, 1)]

    def fake_images(pdf_path, doc_id, start_page, end_page):
        from repair_assistant.qa.page_images import PageImage

        return [
            PageImage(index=1, doc_id=doc_id, page=1, jpeg_bytes=b"JFIF")
        ]

    monkeypatch.setattr(seg, "page_count", fake_page_count)
    monkeypatch.setattr(seg, "outline_parts", fake_outline)
    monkeypatch.setattr(seg, "_load_page_images", fake_images)
    monkeypatch.setattr(seg, "choose_modality", lambda *a, **k: MODALITY_VISION)

    llm = FakeSegmenter({"units": [_unit(1, 1, "Scanned")]})
    proposal = propose_boundaries(pdf, llm=llm, doc_id="scan-doc", force_vision=True)
    assert proposal.modality == MODALITY_VISION
    assert llm.calls and llm.calls[0]["images"]


def test_units_from_spans_uses_thin_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repair_assistant.semantic.validate import ValidatedSpan

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "repair_assistant.semantic.units.extract_page_range_text",
        lambda *a, **k: "Drain pump procedure text",
    )
    spans = [
        ValidatedSpan(
            start_page=1,
            end_page=2,
            start_y=0.0,
            end_y=1.0,
            title="Drain",
            unit_type="repair_procedure",
        )
    ]
    units = units_from_spans(spans, pdf_path=pdf)
    assert units[0].source_text == "Drain pump procedure text"
    assert units[0].page_start == 1
    assert units[0].page_end == 2
    assert not units[0].needs_ocr
