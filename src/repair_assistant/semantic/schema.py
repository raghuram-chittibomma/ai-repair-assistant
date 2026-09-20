"""Strict structured-output schemas for PDF-native segmentation (ADR-0049).

The model proposes page-range markers over the PDF (or page rasters when
scanned). It never emits source prose; ``source_text`` is read back from a
thin PDF extract of the accepted range.
"""

from __future__ import annotations

#: Vocabulary offered to the model. Free-text types are accepted on the way in
#: (a reviewer can retitle anything), but the enum keeps proposals comparable.
UNIT_TYPES: tuple[str, ...] = (
    "diagnostic_procedure",
    "repair_procedure",
    "troubleshooting_table",
    "troubleshooting_flow",
    "specification",
    "component_reference",
    "error_code_reference",
    "warning_with_procedure",
    "installation",
    "overview",
    "other",
)

#: Ambiguous-boundary signals for the human review board. Not a numeric
#: confidence score — a discrete reason the reviewer should look closer.
REVIEW_FLAGS: tuple[str, ...] = (
    "none",
    "ambiguous_boundary",
    "cross_page_dependency",
    "table_relationship",
    "figure_relationship",
    "warning_scope",
    "diagnostic_dependency",
    "other",
)

SEGMENT_SCHEMA: dict = {
    "name": "semantic_segmentation",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "start_page": {"type": "integer"},
                        "end_page": {"type": "integer"},
                        "start_y": {"type": "number"},
                        "end_y": {"type": "number"},
                        "title": {"type": "string"},
                        "unit_type": {"type": "string", "enum": list(UNIT_TYPES)},
                        "rationale": {"type": "string"},
                        "review_flag": {
                            "type": "string",
                            "enum": list(REVIEW_FLAGS),
                        },
                        "review_note": {"type": "string"},
                    },
                    "required": [
                        "start_page",
                        "end_page",
                        "start_y",
                        "end_y",
                        "title",
                        "unit_type",
                        "rationale",
                        "review_flag",
                        "review_note",
                    ],
                },
            },
        },
        "required": ["units"],
    },
}

SEGMENT_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": SEGMENT_SCHEMA,
}

#: Retrieval representation kinds. A fourth kind is additive: add it here and
#: register a builder in ``representations.py``.
REPRESENTATION_KINDS: tuple[str, ...] = ("overview", "facts", "questions")

REPRESENTATIONS_SCHEMA: dict = {
    "name": "retrieval_representations",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overview": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["overview", "facts", "questions"],
    },
}

REPRESENTATIONS_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": REPRESENTATIONS_SCHEMA,
}

ASSIST_SCHEMA: dict = {
    "name": "corpus_assist_suggestion",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rationale": {"type": "string"},
            "overview": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["rationale", "overview", "facts", "questions"],
    },
}

ASSIST_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": ASSIST_SCHEMA,
}
