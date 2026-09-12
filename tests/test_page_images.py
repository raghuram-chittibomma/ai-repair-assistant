"""Gated late-fusion page rasters (ADR-0035) — no live OpenAI."""

from __future__ import annotations

from pathlib import Path

import pytest

from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.qa.context import (
    FIGURE_ATTACHED_NOTE,
    FIGURE_UNREADABLE_NOTE,
    format_evidence,
)
from repair_assistant.qa.env import model_supports_vision
from repair_assistant.qa.generate import build_chat_messages, invoke_complete, messages_for_trace
from repair_assistant.qa.page_images import (
    PageImage,
    PageImageSpec,
    citation_public_dict,
    document_pdf_path,
    figure_page_payloads,
    hit_needs_page_image,
    plan_page_images,
    raster_pdf_page,
    safe_doc_id,
)
from repair_assistant.retrieval.search import Hit


def _hit(**kwargs) -> Hit:
    defaults = {
        "doc_id": "service-manual-w11169652-revb",
        "chunk_id": "p16",
        "text": "F5E2 indicates a lid switch fault.",
        "page": 16,
        "kind": "prose",
        "error_codes": [],
        "publication_number": "W11169652",
        "revision": "B",
        "score": 0.8,
    }
    defaults.update(kwargs)
    return Hit(**defaults)


def _manifest(tmp_path: Path, *, with_pdf: bool) -> Manifest:
    doc = Document(
        data={
            "doc_id": "service-manual-w11169652-revb",
            "title": "Service manual",
            "doc_type": "service_manual",
            "publication_number": "W11169652",
            "revision": "B",
            "provenance": {"local_filename": "W11169652B.pdf"},
        },
        path=tmp_path / "manifest.yaml",
    )
    root = tmp_path
    (root / "corpus" / "documents").mkdir(parents=True)
    if with_pdf:
        (root / "corpus" / "documents" / "W11169652B.pdf").write_bytes(b"%PDF-1.4 placeholder")
    return Manifest(documents=[doc], root=root)


def test_hit_needs_page_image_for_figure_cite_not_plain_code() -> None:
    assert hit_needs_page_image("Check continuity at J36. See Figure 2 on the wiring diagram.")
    assert not hit_needs_page_image("F5E2 indicates the main control cannot detect the lid.")


def test_plan_skips_missing_pdf(tmp_path: Path) -> None:
    hit = _hit(text="See Figure 2 on the wiring diagram.")
    _, citations = format_evidence([hit])
    missing = _manifest(tmp_path, with_pdf=False)
    assert plan_page_images([hit], citations, missing) == []
    assert document_pdf_path(missing, hit.doc_id) is None


def test_plan_caps_unique_pages(tmp_path: Path) -> None:
    hits = [
        _hit(chunk_id="a", page=16, text="See Figure 2 on the wiring diagram."),
        _hit(chunk_id="b", page=16, text="shown in the figure for the latch."),
        _hit(chunk_id="c", page=17, text="See the diagram for J36."),
        _hit(chunk_id="d", page=18, text="See Figure 4 on the wiring diagram."),
        _hit(chunk_id="e", page=19, text="See Figure 5 on the wiring diagram."),
    ]
    _, citations = format_evidence(hits)
    specs = plan_page_images(hits, citations, _manifest(tmp_path, with_pdf=True))
    assert [s.page for s in specs] == [16, 17, 18]
    assert len({(s.doc_id, s.page) for s in specs}) == 3


def test_format_evidence_attached_replaces_unread_for_that_block() -> None:
    hit = _hit(text="Check continuity at J36. See Figure 2 on the wiring diagram.")
    unread, _ = format_evidence([hit])
    assert unread.endswith(FIGURE_UNREADABLE_NOTE)
    attached, _ = format_evidence([hit], attached_indexes={1})
    assert FIGURE_ATTACHED_NOTE in attached
    assert FIGURE_UNREADABLE_NOTE not in attached


def test_model_supports_vision_dated_snapshots() -> None:
    assert model_supports_vision("gpt-4o-mini-2024-07-18")
    assert model_supports_vision("gpt-4.1-mini-2025-04-14")
    assert not model_supports_vision("gpt-3.5-turbo-0125")


def test_build_chat_messages_and_trace_omit_bytes() -> None:
    image = PageImage(index=1, doc_id="doc", page=16, jpeg_bytes=b"jpeg-bytes")
    messages = build_chat_messages("sys", "user text", [image])
    user = messages[1]["content"]
    assert isinstance(user, list)
    assert user[0]["type"] == "text"
    assert any(part.get("type") == "image_url" for part in user)
    url = next(part["image_url"]["url"] for part in user if part.get("type") == "image_url")
    assert url.startswith("data:image/jpeg;base64,")
    trace = messages_for_trace("sys", "user text", [image])
    blob = str(trace)
    assert "jpeg-bytes" not in blob
    assert "data:image" not in blob
    assert "[1] p.16" in trace[1]["content"]


def test_invoke_complete_records_images_on_compatible_client() -> None:
    seen: list[int] = []

    class Recorder:
        def complete(self, system: str, user: str, *, images=None) -> str:
            seen.append(len(images or []))
            return "ok"

    image = PageImage(index=1, doc_id="doc", page=2, jpeg_bytes=b"x")
    assert invoke_complete(Recorder(), "s", "u", [image]) == "ok"
    assert seen == [1]


def test_invoke_complete_falls_back_when_client_ignores_images() -> None:
    class TextOnly:
        def complete(self, system: str, user: str) -> str:
            return "plain"

    image = PageImage(index=1, doc_id="doc", page=2, jpeg_bytes=b"x")
    assert invoke_complete(TextOnly(), "s", "u", [image]) == "plain"


def test_raster_pdf_page_writes_cache(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "page.pdf"
    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    doc.save(pdf_path)
    doc.close()
    cache = tmp_path / "p0001.jpg"
    jpeg = raster_pdf_page(pdf_path, 1, cache)
    assert jpeg
    assert jpeg[:2] == b"\xff\xd8"
    assert cache.is_file()
    assert raster_pdf_page(pdf_path, 1, cache) == jpeg
    assert raster_pdf_page(pdf_path, 9, tmp_path / "missing.jpg") is None


def test_page_image_spec_is_plain() -> None:
    spec = PageImageSpec(index=2, doc_id="doc", page=8)
    assert spec.index == 2


def test_figure_page_payloads_dedupes_and_rejects_unsafe_ids() -> None:
    rows = [
        {"index": 1, "doc_id": "service-manual-w11169652-revb", "page": 48},
        {"index": 2, "doc_id": "service-manual-w11169652-revb", "page": 48},
        {"index": 3, "doc_id": "../secret", "page": 1},
        {"index": 4, "doc_id": "ok-doc", "page": 0},
    ]
    out = figure_page_payloads(rows)
    assert out == [
        {
            "index": 1,
            "doc_id": "service-manual-w11169652-revb",
            "page": 48,
            "url": "/v1/documents/service-manual-w11169652-revb/pages/48/image",
        }
    ]
    assert safe_doc_id("../secret") is None
    assert safe_doc_id("service-manual-w11169652-revb") == "service-manual-w11169652-revb"


def test_citation_public_dict_adds_url_and_bbox() -> None:
    from repair_assistant.qa.context import Citation

    cite = Citation(
        index=1,
        doc_id="tech-sheet-w11320651",
        chunk_id="p8",
        label="W11320651 p.8",
        page=8,
        excerpt="F5E2",
        bbox={"x0": 1, "y0": 2, "x1": 3, "y1": 4},
        page_width=612,
        page_height=792,
    )
    payload = citation_public_dict(cite)
    assert payload["url"] == "/v1/documents/tech-sheet-w11320651/pages/8/image"
    assert payload["bbox"]["x0"] == 1
    assert payload["page_width"] == 612.0
