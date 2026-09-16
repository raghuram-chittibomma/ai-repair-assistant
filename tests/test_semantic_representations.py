"""Retrieval representations and the BGE token guard (ADR-0048 decisions 4-5)."""

from __future__ import annotations

import json

import pytest

from repair_assistant.semantic.representations import (
    BUILDERS,
    MAX_UNIT_CHARS_FOR_PROMPT,
    RepresentationError,
    build_user_prompt,
    edited_representation,
    generate_representations,
    parse_representations,
    register_builder,
)
from repair_assistant.semantic.tokens import (
    BGE_MAX_TOKENS,
    DEFAULT_TOKEN_BUDGET,
    count_tokens,
    estimate_tokens,
    fits,
    overflow,
)
from repair_assistant.semantic.units import SemanticUnit
from tests.semantic_fixtures import (
    LONG_STEP_BODY,
    FakeRepresenter,
)


def _units():
    long_text = ("Step. " + LONG_STEP_BODY + " ") * 40
    return [
        SemanticUnit(
            unit_key="001-drain",
            ordinal=0,
            title="Drain procedure",
            unit_type="repair_procedure",
            page_start=1,
            page_end=2,
            section_path=["DRAIN"],
            source_text=long_text.strip(),
            source_span=["p1@0.0000", "p2@1.0000"],
            content_hash="abc",
        )
    ]


# --- the token guard -------------------------------------------------------


def test_budget_sits_under_the_hard_model_limit() -> None:
    assert DEFAULT_TOKEN_BUDGET < BGE_MAX_TOKENS


def test_estimate_charges_codes_and_part_numbers_extra() -> None:
    assert estimate_tokens("the pump") < estimate_tokens("W11169652 F9E1 CN4-12")


def test_estimate_is_pessimistic_rather_than_optimistic() -> None:
    # A word-count floor: WordPiece never emits fewer pieces than words.
    text = "check the drain pump resistance at the connector"
    assert estimate_tokens(text) >= len(text.split())


def test_a_unit_can_exceed_the_embedder_limit() -> None:
    """The architectural premise: units are not sized to 512 tokens."""
    procedure = _units()[0]
    assert count_tokens(procedure.source_text) > BGE_MAX_TOKENS
    assert not fits(procedure.source_text)
    assert overflow(procedure.source_text) > 0


def test_short_text_fits_and_reports_no_overflow() -> None:
    assert fits("Check the drain hose for kinks.")
    assert overflow("Check the drain hose for kinks.") == 0


# --- parsing ---------------------------------------------------------------


def test_three_representations_are_built_for_one_parent() -> None:
    unit = _units()[0]
    raw = FakeRepresenter().complete("sys", "user")
    reps = parse_representations(raw, unit)

    assert [r.rep_kind for r in reps] == ["overview", "facts", "questions"]
    assert all(r.unit_key == unit.unit_key for r in reps)
    assert {r.chunk_id for r in reps} == {
        f"u-{unit.unit_key}-overview",
        f"u-{unit.unit_key}-facts",
        f"u-{unit.unit_key}-questions",
    }
    questions = next(r for r in reps if r.rep_kind == "questions")
    assert "Why won't the washer drain?" in questions.text


def test_empty_kinds_are_dropped_not_stored_blank() -> None:
    unit = _units()[0]
    raw = json.dumps({"overview": "About the drain pump.", "facts": [], "questions": []})
    reps = parse_representations(raw, unit)
    assert [r.rep_kind for r in reps] == ["overview"]


@pytest.mark.parametrize(
    "raw",
    ["", "not json", json.dumps(["a"]), json.dumps({"overview": "", "facts": []})],
)
def test_unusable_representation_output_raises(raw: str) -> None:
    with pytest.raises(RepresentationError):
        parse_representations(raw, _units()[0])


def test_a_new_representation_kind_is_additive() -> None:
    """Registering a builder is enough; no retrieval or persistence change."""
    unit = _units()[0]
    original = dict(BUILDERS)
    try:
        register_builder("synonyms", lambda p: str(p.get("synonyms") or "").strip())
        reps = parse_representations(
            json.dumps(
                {
                    "overview": "About the drain pump.",
                    "facts": ["drain pump"],
                    "questions": ["Why won't it drain?"],
                    "synonyms": "sump pump, discharge pump",
                }
            ),
            unit,
        )
        by_kind = {r.rep_kind: r for r in reps}
        assert "synonyms" in by_kind
        assert by_kind["synonyms"].text == "sump pump, discharge pump"
        assert by_kind["synonyms"].chunk_id == f"u-{unit.unit_key}-synonyms"
    finally:
        BUILDERS.clear()
        BUILDERS.update(original)


# --- prompting -------------------------------------------------------------


def test_prompt_carries_the_unit_content_and_provenance() -> None:
    unit = _units()[0]
    unit.source_text = "WARNING: Disconnect power before servicing.\n" + unit.source_text
    prompt = build_user_prompt(unit)
    assert unit.title in prompt
    assert "pp.1-2" in prompt
    assert "WARNING: Disconnect power" in prompt


def test_prompt_bounds_a_very_large_unit() -> None:
    unit = _units()[0]
    unit.source_text = "x " * (MAX_UNIT_CHARS_FOR_PROMPT)
    prompt = build_user_prompt(unit)
    assert "[unit continues]" in prompt
    assert len(prompt) < MAX_UNIT_CHARS_FOR_PROMPT + 2000


def test_retry_prompt_asks_for_a_tighter_representation() -> None:
    prompt = build_user_prompt(_units()[0], tighten=True)
    assert "too long to embed" in prompt


# --- generation and the reject-not-truncate rule --------------------------


def test_generation_keeps_every_kind_when_all_fit() -> None:
    unit = _units()[0]
    fake = FakeRepresenter()
    result = generate_representations(unit, llm=fake, max_attempts=2)

    assert result.attempts == 1, "no retry needed"
    assert [r.rep_kind for r in result.representations] == [
        "overview",
        "facts",
        "questions",
    ]
    assert not result.over_limit
    assert all(r.tokens > 0 for r in result.representations)


def test_an_over_limit_representation_is_regenerated_not_truncated() -> None:
    unit = _units()[0]
    fake = FakeRepresenter(long_facts=True)
    result = generate_representations(unit, llm=fake, max_attempts=2)

    assert result.attempts == 2, "the over-budget facts list forced a retry"
    facts = next(r for r in result.representations if r.rep_kind == "facts")
    assert not facts.over_limit
    assert facts.tokens <= DEFAULT_TOKEN_BUDGET
    # The whole point: the accepted text is a shorter generation, not a prefix.
    assert not LONG_STEP_BODY.startswith(facts.text)
    assert "cut every word" in fake.calls[-1]


def test_a_representation_that_never_fits_is_flagged_rather_than_cut() -> None:
    unit = _units()[0]

    class AlwaysLong:
        def complete(self, system: str, user: str) -> str:
            return json.dumps(
                {
                    "overview": "Short and fine.",
                    "facts": [f"connector CN{n} resistance {n}.4 ohms" for n in range(200)],
                    "questions": ["Why won't it drain?"],
                }
            )

    result = generate_representations(unit, llm=AlwaysLong(), max_attempts=2)
    over = {r.rep_kind for r in result.over_limit}
    assert over == {"facts"}
    facts = next(r for r in result.representations if r.rep_kind == "facts")
    assert facts.tokens > DEFAULT_TOKEN_BUDGET
    assert facts.text.endswith("resistance 199.4 ohms"), "text kept whole for review"
    # A kind that already fitted is not discarded because another failed.
    assert not next(r for r in result.representations if r.rep_kind == "overview").over_limit


def test_a_fitting_kind_is_not_replaced_by_a_retry() -> None:
    unit = _units()[0]
    fake = FakeRepresenter(long_facts=True, overview="First overview.")
    result = generate_representations(unit, llm=fake, max_attempts=2)
    overview = next(r for r in result.representations if r.rep_kind == "overview")
    assert overview.text == "First overview."


def test_a_reviewer_edit_is_measured_the_same_way() -> None:
    fitting = edited_representation("001-drain", "overview", "  Drain pump test.  ")
    assert fitting.text == "Drain pump test."
    assert fitting.origin == "human"
    assert fitting.edited
    assert not fitting.over_limit

    too_long = edited_representation(
        "001-drain", "facts", " ".join(f"CN{n} {n}.4 ohms" for n in range(300))
    )
    assert too_long.over_limit
