"""A synthetic parsed document with the awkward shapes real manuals have.

Covers a procedure that crosses a page break, a table that continues onto the
next page, a warning that governs the procedure after it, and enough text that
one unit exceeds the embedder's 512-token budget.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from repair_assistant.ingest.parsed import ParsedChunk, ParsedDocument


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def chunk(
    chunk_id: str,
    text: str,
    *,
    page: int,
    kind: str = "prose",
    section_path: list[str] | None = None,
    body_text: str | None = None,
    error_codes: list[str] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    doc_id: str = "ci-semantic-doc",
) -> ParsedChunk:
    metadata: dict[str, Any] = {"section_path": list(section_path or [])}
    metadata["body_text"] = body_text if body_text is not None else text
    if extra_metadata:
        metadata.update(extra_metadata)
    return ParsedChunk(
        chunk_id=chunk_id,
        text=text,
        page=page,
        kind=kind,
        error_codes=list(error_codes or []),
        language="en-US",
        doc_id=doc_id,
        publication_number="SYNTH-CI-SEM",
        revision="A",
        metadata=metadata,
        content_hash=_hash(text),
    )


#: A long block so the unit containing it cannot fit in 512 BGE tokens.
LONG_STEP_BODY = " ".join(
    f"Step {n}: measure the winding resistance at connector CN{n} and confirm the "
    f"reading falls between {n}.4 and {n}.9 ohms before continuing to the next "
    f"terminal pair on the drive motor harness."
    for n in range(1, 26)
)


def parsed_document(doc_id: str = "ci-semantic-doc") -> ParsedDocument:
    """Nine anchors across three pages, in reading order."""
    drain = ["DRAIN SYSTEM"]
    table = ["ERROR CODE DISPLAY"]
    chunks = [
        chunk(
            "p1-heading-drain",
            "Section: DRAIN SYSTEM",
            page=1,
            kind="heading",
            section_path=drain,
            body_text="DRAIN SYSTEM",
            doc_id=doc_id,
        ),
        chunk(
            "p1-prose-warning",
            "WARNING: Disconnect power before servicing the drain pump. "
            "Failure to do so can result in electrical shock or death.",
            page=1,
            section_path=drain,
            doc_id=doc_id,
        ),
        chunk(
            "p1-procedure-head",
            "TEST #7: Drain Pump. Perform this test when the washer will not drain.",
            page=1,
            kind="procedure",
            section_path=drain,
            doc_id=doc_id,
        ),
        # The procedure continues onto page 2: never cut between these two.
        chunk(
            "p2-procedure-tail",
            LONG_STEP_BODY,
            page=2,
            kind="procedure",
            section_path=drain,
            doc_id=doc_id,
        ),
        chunk(
            "p2-prose-result",
            "If any reading is out of range, replace the drain pump and retest.",
            page=2,
            section_path=drain,
            doc_id=doc_id,
        ),
        chunk(
            "p2-heading-codes",
            "Section: ERROR CODE DISPLAY",
            page=2,
            kind="heading",
            section_path=table,
            body_text="ERROR CODE DISPLAY",
            doc_id=doc_id,
        ),
        chunk(
            "p2-table_row-f9e1",
            "F9E1 | Long drain | Check the drain hose for kinks.",
            page=2,
            kind="table_row",
            section_path=table,
            error_codes=["F9E1"],
            extra_metadata={"headers": ["Error Code", "Problem", "Checks & Tests"]},
            doc_id=doc_id,
        ),
        # The table continues onto page 3: the header row lives on page 2.
        chunk(
            "p3-table_row-f9e2",
            "F9E2 | Drain pump open circuit | Perform TEST #7.",
            page=3,
            kind="table_row",
            section_path=table,
            error_codes=["F9E2"],
            extra_metadata={"headers": ["Error Code", "Problem", "Checks & Tests"]},
            doc_id=doc_id,
        ),
        chunk(
            "p3-prose-tail",
            "Record the resistance readings on the service ticket.",
            page=3,
            section_path=table,
            doc_id=doc_id,
        ),
    ]
    return ParsedDocument(
        doc_id=doc_id,
        path=Path("ci"),
        meta={
            "doc_id": doc_id,
            "publication_number": "SYNTH-CI-SEM",
            "revision": "A",
            "extractor": "ci",
        },
        chunks=chunks,
    )


def write_parsed(tmp_path: Path, doc_id: str = "ci-semantic-doc") -> Path:
    """Materialise the fixture as corpus/parsed/<doc_id>/ on disk."""
    parsed = parsed_document(doc_id)
    dest = tmp_path / "parsed" / doc_id
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for item in parsed.chunks:
            payload = {
                "chunk_id": item.chunk_id,
                "text": item.text,
                "page": item.page,
                "kind": item.kind,
                "error_codes": item.error_codes,
                "language": item.language,
                "doc_id": item.doc_id,
                "publication_number": item.publication_number,
                "revision": item.revision,
                "metadata": item.metadata,
                "content_hash": item.content_hash,
            }
            fh.write(json.dumps(payload) + "\n")
    (dest / "meta.json").write_text(json.dumps(parsed.meta, indent=2), encoding="utf-8")
    return dest


#: A good PDF-native tiling for a 3-page window (ADR-0049).
GOOD_UNITS: list[dict] = [
    {
        "start_page": 1,
        "end_page": 2,
        "start_y": 0.0,
        "end_y": 1.0,
        "title": "TEST #7: Drain Pump",
        "unit_type": "warning_with_procedure",
        "rationale": "The shock warning governs every step of this test.",
        "review_flag": "none",
        "review_note": "",
    },
    {
        "start_page": 3,
        "end_page": 3,
        "start_y": 0.0,
        "end_y": 1.0,
        "title": "Drain error codes F9E1 and F9E2",
        "unit_type": "troubleshooting_table",
        "rationale": "The continuation row needs the header row above it.",
        "review_flag": "none",
        "review_note": "",
    },
]


class FakeSegmenter:
    """Returns canned segmentation payloads, one per window."""

    def __init__(self, payloads: list[dict] | dict) -> None:
        self.payloads = payloads if isinstance(payloads, list) else [payloads]
        self.calls: list[tuple] = []

    def complete(self, system: str, user: str, *, images=None, pdf_path=None) -> str:
        self.calls.append((system, user, images, pdf_path))
        index = min(len(self.calls) - 1, len(self.payloads) - 1)
        return json.dumps(self.payloads[index])


class FakeRepresenter:
    """Returns representations derived from the unit text handed to it."""

    def __init__(self, *, long_facts: bool = False, overview: str | None = None) -> None:
        self.long_facts = long_facts
        self.overview = overview
        self.calls: list[str] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append(user)
        tightened = "cut every word that carries no search value" in user
        facts = ["drain pump", "F9E1 long drain", "CN4 resistance 1.4 to 1.9 ohms"]
        if self.long_facts and not tightened:
            facts = [
                f"connector CN{n} winding resistance between {n}.4 and {n}.9 ohms "
                f"measured at the drive motor harness terminal pair {n}"
                for n in range(1, 60)
            ]
        return json.dumps(
            {
                "overview": self.overview
                or "How to test the drain pump when the washer will not drain.",
                "facts": facts,
                "questions": [
                    "Why won't the washer drain?",
                    "What causes error F9E1?",
                    "How do I test the drain pump?",
                ],
            }
        )

PAGE_TEXTS = {
    1: "WARNING: Disconnect power. TEST #7 Drain Pump. Step 1 check the hose.",
    2: "Step 2 measure CN4 resistance. Expected result: 1.4 to 1.9 ohms.",
    3: "Error codes. F9E1 long drain. F9E2 drain timeout. See table notes.",
}


def write_stub_pdf(path: Path, *, pages: int = 3) -> Path:
    """Minimal multi-page PDF with extractable text for curator tests."""
    import fitz

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for page_no in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            PAGE_TEXTS.get(page_no, f"Page {page_no} content."),
            fontsize=11,
        )
    doc.save(str(path))
    doc.close()
    return path


def patch_pdf_segmentation(monkeypatch, pdf_path: Path, *, pages: int = 3) -> None:
    """Force a single native-PDF window over ``pages`` for fake segmenters."""
    import repair_assistant.semantic.segment as seg
    from repair_assistant.semantic.pdf_extract import PdfOutlinePart

    monkeypatch.setattr(seg, "page_count", lambda _p: pages)
    monkeypatch.setattr(
        seg,
        "outline_parts",
        lambda _p, *, max_pages_per_part=40: [PdfOutlinePart("All", 1, pages)],
    )
    monkeypatch.setattr(seg, "choose_modality", lambda *a, **k: seg.MODALITY_NATIVE_PDF)

    def fake_write(src, *, start_page, end_page, dest):
        dest.write_bytes(Path(src).read_bytes())
        return dest

    monkeypatch.setattr(seg, "write_pdf_part", fake_write)

    def fake_extract(path, *, start_page, end_page):
        parts = [
            PAGE_TEXTS.get(p, f"Page {p}") for p in range(start_page, end_page + 1)
        ]
        return "\n\n".join(parts)

    monkeypatch.setattr(
        "repair_assistant.semantic.units.extract_page_range_text", fake_extract
    )
    monkeypatch.setattr(
        "repair_assistant.semantic.pdf_extract.extract_page_range_text", fake_extract
    )

