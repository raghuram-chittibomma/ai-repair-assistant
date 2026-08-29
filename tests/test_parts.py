"""Parts-list linkage for a concluded diagnosis (review R42)."""

from __future__ import annotations

from pathlib import Path

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.qa.parts import related_parts_note
from repair_assistant.retrieval.search import Hit


def test_related_parts_note_names_list_and_numbers() -> None:
    manifest = Manifest(
        documents=[
            Document(
                data={
                    "doc_id": "parts-list-w11320547",
                    "title": "Repair Parts List",
                    "doc_type": "parts_list",
                    "corpus": {"role": "primary"},
                    "publication_number": "W11320547",
                    "revision": "C",
                    "applicability": {
                        "models": ["WFW5620HW0"],
                        "serial_ranges": [{"scope": "all"}],
                    },
                },
                path=Path("parts-list-w11320547.yaml"),
            )
        ]
    )
    hit = Hit(
        doc_id="parts-list-w11320547",
        chunk_id="p3",
        text="Door lock assembly W10855462",
        page=3,
        kind="table_row",
        error_codes=[],
        publication_number="W11320547",
        revision="C",
        score=0.8,
    )
    note = related_parts_note(
        [hit], manifest, Appliance(model="WFW5620HW0")
    )
    assert note is not None
    assert "W11320547" in note
    assert "W10855462" in note
    assert related_parts_note([hit], manifest, Appliance(model="WFW9999HW0")) is None
