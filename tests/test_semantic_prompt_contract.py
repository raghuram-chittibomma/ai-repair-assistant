"""Segmentation prompt/schema behaviour for PDF-native markers (ADR-0049)."""

from __future__ import annotations

import json

from repair_assistant.prompts import semantic_segment
from repair_assistant.semantic.schema import REVIEW_FLAGS, SEGMENT_SCHEMA
from repair_assistant.semantic.segment import parse_proposal
from repair_assistant.semantic.validate import validate


def _prompt() -> str:
    return " ".join(semantic_segment().split())


def test_prompt_keeps_the_technician_retrieval_question() -> None:
    text = _prompt()
    assert "technician retrieving this unit by itself" in text
    assert "Never write, quote, paraphrase, or correct the source text" in text
    assert "start_page" in text and "end_page" in text


def test_prompt_uses_page_markers_not_anchors() -> None:
    text = _prompt()
    assert "anchor id" not in text.lower()
    assert "page range" in text or "start_page" in text
    assert "0.0 = top" in text or "0.0=top" in text.replace(" ", "")


def test_prompt_does_not_treat_a_table_row_as_a_normal_unit() -> None:
    text = _prompt()
    assert "Size is determined by meaning" in text
    assert "do not treat a single table row as a unit" in text


def test_prompt_does_not_split_every_numbered_test() -> None:
    text = _prompt()
    assert "forms one troubleshooting or diagnostic flow" in text
    assert "can reasonably be understood and used on its own" in text


def test_prompt_has_an_independent_use_over_merge_guard() -> None:
    text = _prompt()
    assert "Do not merge material merely because it shares the same chapter" in text
    assert "independently retrieved knowledge unit" in text


def test_prompt_asks_for_review_flags_not_numeric_confidence() -> None:
    text = _prompt()
    assert "review_flag" in text
    assert "confidence" not in text.lower() or "false certainty" in text


def test_schema_requires_page_markers() -> None:
    props = SEGMENT_SCHEMA["schema"]["properties"]["units"]["items"]["properties"]
    assert "start_page" in props and "end_page" in props
    assert "start_y" in props and "end_y" in props
    assert "start_anchor" not in props
    required = SEGMENT_SCHEMA["schema"]["properties"]["units"]["items"]["required"]
    assert "start_page" in required and "review_flag" in required
    assert set(REVIEW_FLAGS) == set(props["review_flag"]["enum"])


def test_tiling_pages_validates() -> None:
    raw = {
        "units": [
            {
                "start_page": 1,
                "end_page": 2,
                "start_y": 0.0,
                "end_y": 1.0,
                "title": "Procedure",
                "unit_type": "diagnostic_procedure",
                "rationale": "one flow",
                "review_flag": "none",
                "review_note": "",
            },
            {
                "start_page": 3,
                "end_page": 3,
                "start_y": 0.0,
                "end_y": 1.0,
                "title": "Codes",
                "unit_type": "error_code_reference",
                "rationale": "table",
                "review_flag": "none",
                "review_note": "",
            },
        ]
    }
    units = parse_proposal(json.dumps(raw))
    report = validate(units, window_start=1, window_end=3)
    assert report.ok
