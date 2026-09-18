"""Hybrid semantic PDF/raster attachments at generate time (ADR-0050/0051)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz

from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.qa.context import Citation, evidence_text, format_evidence
from repair_assistant.qa.generate import AskPrep, interleaved_user_content, stream_from_prep
from repair_assistant.qa.page_images import PageImage
from repair_assistant.qa.semantic_evidence import (
    SEMANTIC_LAYOUT_NOTE,
    attach_semantic_pdf_evidence,
)
from repair_assistant.retrieval.search import Hit


def _hit(**kwargs) -> Hit:
    defaults = {
        "doc_id": "install-doc",
        "chunk_id": "008-unit",
        "text": "Thin source text for the unit. Remove transport bolts before use.",
        "page": 2,
        "kind": "semantic_unit",
        "error_codes": [],
        "publication_number": "W11156977",
        "revision": "D",
        "score": 0.9,
        "unit_id": 1,
        "rep_kind": None,
        "metadata": {
            "page_start": 2,
            "page_end": 3,
            "unit_title": "Install",
            "unit_key": "005-installation-instructions",
            "unit_type": "installation",
        },
    }
    defaults.update(kwargs)
    return Hit(**defaults)


def _cite(hit: Hit, index: int = 1) -> Citation:
    return Citation(
        index=index,
        doc_id=hit.doc_id,
        chunk_id=hit.chunk_id,
        label="label",
        page=hit.page,
        excerpt=hit.text[:80],
        block_text=hit.text,
    )


def _manifest_with_pdf(tmp_path: Path, *, pages: int = 3) -> tuple[Manifest, Path]:
    docs_dir = tmp_path / "corpus" / "documents"
    docs_dir.mkdir(parents=True)
    pdf_path = docs_dir / "install.pdf"
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content")
    doc.save(str(pdf_path))
    doc.close()
    document = Document(
        path=tmp_path / "manifest" / "install-doc.yaml",
        data={
            "doc_id": "install-doc",
            "title": "Install",
            "doc_type": "installation_instructions",
            "publication_number": "W11156977",
            "revision": "D",
            "provenance": {"local_filename": "install.pdf"},
        },
    )
    manifest = Manifest(documents=[document], excluded=[], root=tmp_path)
    return manifest, pdf_path


def test_structured_chunk_sends_full_text_over_2k() -> None:
    hit = _hit(
        kind="table_row",
        unit_id=None,
        text="ROW " * 600,
        metadata={
            "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
            "page_width": 612,
            "page_height": 792,
        },
    )
    assert len(hit.text) > 2000
    assert evidence_text(hit) == hit.text.strip()
    _, citations = format_evidence([hit])
    assert citations[0].block_text == hit.text.strip()


def test_semantic_stub_keeps_full_extract_on_citation() -> None:
    hit = _hit()
    body, citations = format_evidence([hit], semantic_attached_indexes={1})
    assert "modality: semantic_pdf" in body
    assert "unit: 005-installation-instructions (installation)" in body
    assert "Remove transport bolts" not in body
    assert citations[0].block_text == hit.text.strip()
    assert "Remove transport bolts" in citations[0].block_text


def test_semantic_attach_failure_falls_back_to_full_text() -> None:
    hit = _hit()
    body, citations = format_evidence([hit], semantic_attached_indexes=frozenset())
    assert "modality: semantic_text_fallback" in body
    assert "Remove transport bolts" in body
    assert citations[0].block_text == hit.text.strip()


def test_text_pdf_unit_gets_native_page_range_part(tmp_path: Path, monkeypatch) -> None:
    manifest, _ = _manifest_with_pdf(tmp_path)
    monkeypatch.setattr(
        "repair_assistant.qa.semantic_evidence.inspect",
        lambda _path: SimpleNamespace(looks_scanned=False),
    )
    hit = _hit()
    attach = attach_semantic_pdf_evidence([hit], [_cite(hit)], manifest)
    assert len(attach.pdf_paths) == 1
    assert attach.pdf_paths[0].is_file()
    assert attach.pdf_by_index[1] == attach.pdf_paths[0]
    assert attach.attached_indexes == {1}
    assert not attach.page_images
    assert SEMANTIC_LAYOUT_NOTE in attach.notes
    with fitz.open(str(attach.pdf_paths[0])) as sliced:
        assert sliced.page_count == 2
    attach.cleanup()
    assert not attach.pdf_paths[0].is_file()


def test_scanned_pdf_unit_gets_page_rasters(tmp_path: Path, monkeypatch) -> None:
    manifest, _ = _manifest_with_pdf(tmp_path)
    monkeypatch.setattr(
        "repair_assistant.qa.semantic_evidence.inspect",
        lambda _path: SimpleNamespace(looks_scanned=True),
    )
    monkeypatch.setenv("REPAIR_SEMANTIC_EVIDENCE_MAX_PAGES", "8")
    hit = _hit()
    attach = attach_semantic_pdf_evidence([hit], [_cite(hit)], manifest)
    assert attach.pdf_paths == []
    assert len(attach.page_images) == 2
    assert attach.attached_indexes == {1}
    assert {img.page for img in attach.page_images} == {2, 3}
    assert all(img.index == 1 for img in attach.page_images)


def test_missing_pdf_does_not_mark_attached(tmp_path: Path) -> None:
    document = Document(
        path=tmp_path / "manifest" / "install-doc.yaml",
        data={
            "doc_id": "install-doc",
            "title": "Install",
            "doc_type": "installation_instructions",
            "publication_number": "W11156977",
            "revision": "D",
            "provenance": {"local_filename": "missing.pdf"},
        },
    )
    manifest = Manifest(documents=[document], excluded=[], root=tmp_path)
    hit = _hit()
    attach = attach_semantic_pdf_evidence([hit], [_cite(hit)], manifest)
    assert attach.attached_indexes == set()
    assert attach.pdf_paths == []


def test_interleaved_user_content_tags_attachments_by_cite_index() -> None:
    pdf = Path("cite2-install-p6-9.pdf")
    images = [
        PageImage(index=1, doc_id="d", page=3, jpeg_bytes=b"\xff\xd8fake"),
    ]
    parts = interleaved_user_content(
        "Question: q\n\n<<<MANUFACTURER_EVIDENCE>>>…",
        images=images,
        pdf_paths=[pdf],
        pdf_file_ids={2: "file-abc"},
    )
    texts = [p.get("text") for p in parts if p.get("type") == "text"]
    assert texts[0].startswith("Question: q")
    assert texts[1] == "Attachment for evidence [1]:"
    assert texts[2] == "(PDF page 3)"
    assert texts[3] == "Attachment for evidence [2]:"
    assert any(p.get("type") == "file" and p["file"]["file_id"] == "file-abc" for p in parts)
    assert any(p.get("type") == "image_url" for p in parts)


def test_messages_for_trace_prefixes_pdf_attachment_fingerprint() -> None:
    from repair_assistant.qa.generate import messages_for_trace

    traced = messages_for_trace(
        "sys",
        "Question: q\n\nEvidence…",
        pdf_paths=[Path("cite1-install-p15-19.pdf")],
    )
    content = traced[1]["content"]
    assert content.startswith(
        "[attachments; 1 PDF page-range file(s): cite1-install-p15-19.pdf]"
    )
    assert "Question: q" in content


def test_generation_trace_input_embeds_langfuse_pdf_media(
    tmp_path: Path, monkeypatch
) -> None:
    from langfuse.media import LangfuseMedia

    from repair_assistant.qa.generate import generation_trace_input

    pdf = tmp_path / "cite1-install-p15-19.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    payload = generation_trace_input(
        "sys", "user text", pdf_paths=[pdf]
    )
    assert "messages" in payload
    assert payload["messages"][1]["content"].startswith("[attachments;")
    parts = payload["native_pdf_parts"]
    assert list(parts) == ["cite1-install-p15-19.pdf"]
    assert isinstance(parts["cite1-install-p15-19.pdf"], LangfuseMedia)


def test_prepare_trace_value_preserves_langfuse_media(monkeypatch) -> None:
    from langfuse.media import LangfuseMedia

    from repair_assistant.observability.langfuse_tracing import prepare_trace_value

    monkeypatch.setenv("REPAIR_TRACE_REDACT_SERIAL", "1")
    media = LangfuseMedia(content_bytes=b"%PDF-1.4", content_type="application/pdf")
    out = prepare_trace_value(
        {
            "native_pdf_parts": {"slice.pdf": media},
            "serial": "AB12345678",
            "note": "x" * 50,
        },
        max_chars=20,
    )
    assert out["native_pdf_parts"]["slice.pdf"] is media
    assert out["serial"] == "[serial]"
    assert out["note"].endswith("chars total]")


def test_stream_from_prep_uses_complete_when_pdfs_attached() -> None:
    from repair_assistant.safety.policy import Audience, SafetyAction, SafetyAssessment

    calls: list[str] = []

    class FakeLLM:
        model = "fake"
        prompt_name = "ask_system"

        def complete(self, system, user, **kwargs):
            calls.append("complete")
            assert kwargs.get("pdf_paths")
            return (
                '{"answer":"ok","claims":[{"text":"ok","evidence_index":1}],'
                '"abstain":false}'
            )

        def stream(self, system, user, **kwargs):
            calls.append("stream")
            yield "should-not-run"

    prep = AskPrep(
        question="q",
        appliance=None,
        assessment=SafetyAssessment(
            action=SafetyAction.ALLOW,
            rule_id="allow",
            reason="",
            audience=Audience.OWNER,
            prompt_directive="",
        ),
        available=[
            Citation(
                index=1,
                doc_id="d",
                chunk_id="c",
                label="L",
                page=1,
                excerpt="e",
                block_text="e",
            )
        ],
        evidence_pdfs=[Path("dummy.pdf")],
        system="sys",
        user_prompt="user",
    )
    events = list(stream_from_prep(prep, llm=FakeLLM()))  # type: ignore[arg-type]
    assert calls == ["complete"]
    assert any(ev.get("type") == "done" for ev in events)


def test_trace_evidence_two_phase_stub_when_pdf_ok(tmp_path: Path, monkeypatch) -> None:
    """Light install-style smoke: attach succeeds → fence stub, ledger full."""
    from repair_assistant.qa.generate import _trace_evidence

    manifest, _ = _manifest_with_pdf(tmp_path)
    monkeypatch.setattr(
        "repair_assistant.qa.semantic_evidence.inspect",
        lambda _path: SimpleNamespace(looks_scanned=False),
    )
    monkeypatch.setattr(
        "repair_assistant.qa.generate.llm_vision_model",
        lambda: None,
    )
    hit = _hit()
    evidence, citations, images, semantic = _trace_evidence(
        [hit], query="How do I remove the transport bolts?", manifest=manifest
    )
    assert semantic.attached_indexes == {1}
    assert len(semantic.pdf_paths) == 1
    assert "modality: semantic_pdf" in evidence
    fence = evidence.split("<<<END_MANUFACTURER_EVIDENCE>>>")[0]
    assert "Remove transport bolts" not in fence
    assert citations[0].block_text == hit.text.strip()
    assert images == []
    semantic.cleanup()
