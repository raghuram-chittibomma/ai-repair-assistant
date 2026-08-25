"""Tests for model matching, serial decoding, and document applicability.

The serial ranges and model lists asserted here are transcribed from real
Whirlpool service pointers, not invented. Where a test encodes a fact about the
documents, the source is named in a comment so a future reader can re-check it.
"""

from __future__ import annotations

import pytest

from repair_assistant.corpus.applicability import (
    Appliance,
    Serial,
    SerialFormatError,
    SerialRange,
    base_model,
    document_applies,
    engineering_digit,
    model_matches,
    year_code_for,
    years_for_code,
)

# ---------------------------------------------------------------------------
# Model matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "model", "expected"),
    [
        # '*' as Whirlpool uses it: any engineering digit of a base model.
        ("WFW5620HW*", "WFW5620HW0", True),
        ("WFW5620HW*", "WFW5620HW3", True),
        ("WFW5620HW*", "WFW5620HW", True),
        # A different base model must not match, even though it differs by one
        # character. WFW5622HW is the Maytag Commercial sibling, not our unit.
        ("WFW5620HW*", "WFW5622HW0", False),
        ("WFW5620HW*", "WFW6620HW0", False),
        # Family-wide patterns used by generic knowledge base articles.
        ("WFW*", "WFW5620HW0", True),
        ("WFW*", "WTW4816FW0", False),
        # Exact patterns stay exact: the parts list covers HW0 only.
        ("WFW5620HW0", "WFW5620HW0", True),
        ("WFW5620HW0", "WFW5620HW3", False),
        # Case and whitespace are normalised.
        ("WFW5620HW*", " wfw5620hw0 ", True),
    ],
)
def test_model_matches(pattern, model, expected):
    assert model_matches(pattern, model) is expected


def test_malformed_pattern_is_rejected():
    with pytest.raises(ValueError):
        model_matches("WFW-5620*", "WFW5620HW0")


def test_base_model_strips_only_a_trailing_digit():
    assert base_model("WFW5620HW0") == "WFW5620HW"
    # 'W' here denotes the colour white, not an engineering digit. Stripping it
    # would silently merge genuinely different models.
    assert base_model("WFW5620HW") == "WFW5620HW"


def test_engineering_digit():
    assert engineering_digit("WFW5620HW0") == "0"
    assert engineering_digit("WFW5620HW3") == "3"
    assert engineering_digit("WFW5620HW") is None


# ---------------------------------------------------------------------------
# Serial numbers
# ---------------------------------------------------------------------------


def test_year_code_cycle_matches_documented_values():
    assert year_code_for(2018) == "8"
    assert year_code_for(2019) == "9"
    assert year_code_for(2020) == "X"
    assert year_code_for(2023) == "C"
    assert year_code_for(2024) == "D"
    # 1990 and 2020 share a code: the cycle is 30 years long.
    assert year_code_for(1990) == year_code_for(2020)


def test_year_codes_are_decade_ambiguous():
    """A serial cannot date itself. This is a real property, not a limitation."""
    assert years_for_code("X") == [1990, 2020]
    assert years_for_code("C") == [1993, 2023]
    assert Serial.parse("CX10xxxx").is_ambiguous


@pytest.mark.parametrize(
    ("raw", "division", "year_code", "week"),
    [
        # All four transcribed from genuine service pointers.
        ("CF81500000", "CF", "8", 15),   # W11395614, WFW3090GW2 range start
        ("CX10xxxx", "C", "X", 10),      # W11533288, commercial washer range start
        ("CC01xxxxx", "C", "C", 1),      # W11766193, top load range start
        ("CD05xxxxx", "C", "D", 5),      # W11766193, top load range end
    ],
)
def test_serial_parsing(raw, division, year_code, week):
    serial = Serial.parse(raw)
    assert serial.division == division
    assert serial.year_code == year_code
    assert serial.week == week


def test_serial_resolution_uses_outside_context():
    serial = Serial.parse("CX10xxxx")
    # Given a model introduced in 2018, 'X' must mean 2020 and not 1990.
    assert serial.resolve_year(2018) == 2020
    assert serial.resolve_year(1985) == 1990


@pytest.mark.parametrize("bad", ["", "12345", "C", "CF8", "CF89900000", "not-a-serial"])
def test_malformed_serials_are_rejected(bad):
    with pytest.raises(SerialFormatError):
        Serial.parse(bad)


def test_division_prefix_length_is_resolved_by_the_week_number():
    """One- and two-letter division prefixes are ambiguous from characters alone.

    Both readings parse structurally; only one yields a legal week, and that is
    what decides. Getting this wrong silently shifts the year and the week, and
    would put serials in or out of a documented range for no visible reason.
    """
    two_letter = Serial.parse("CF81500000")
    assert (two_letter.division, two_letter.year_code, two_letter.week) == ("CF", "8", 15)

    one_letter = Serial.parse("CX090000")
    assert (one_letter.division, one_letter.year_code, one_letter.week) == ("C", "X", 9)


# ---------------------------------------------------------------------------
# Serial range containment
# ---------------------------------------------------------------------------

# From TSP W11395614: "For Model WFW3090GW2: CF81500000 - CF84510000"
W11395614_RANGE = SerialRange(
    start=Serial.parse("CF81500000"),
    end=Serial.parse("CF84510000"),
    model="WFW3090GW2",
)


@pytest.mark.parametrize(
    ("serial", "inside"),
    [
        ("CF81500000", True),   # inclusive lower bound
        ("CF84510000", True),   # inclusive upper bound
        ("CF83000000", True),   # week 30, comfortably inside
        ("CF81400000", False),  # week 14, one week before the range opens
        ("CF84600000", False),  # week 46, just past the end
        ("CF91500000", False),  # right week, wrong year (2019 not 2018)
    ],
)
def test_range_containment(serial, inside):
    assert W11395614_RANGE.contains(serial, reference_year=2018) is inside


def test_different_plant_prefix_is_never_in_range():
    """Matching digits from a different division are a different production line."""
    assert not W11395614_RANGE.contains("CS83000000", reference_year=2018)


def test_wildcard_bounds_expand_in_the_right_direction():
    # From W11533288: "CX10xxxx to CX27xxxx".
    span = SerialRange(start=Serial.parse("CX10xxxx"), end=Serial.parse("CX27xxxx"))
    assert span.contains("CX150000", reference_year=2020)
    assert not span.contains("CX280000", reference_year=2020)
    assert not span.contains("CX090000", reference_year=2020)


def test_scope_all_contains_everything():
    assert SerialRange.all_serials().contains("CF81500000", reference_year=2018)


# ---------------------------------------------------------------------------
# Document-level applicability
# ---------------------------------------------------------------------------

TSP_W11375982 = {
    "temporal": {"publication_date": "2019-06"},
    "applicability": {
        "models": ["WFW5620HW*", "MHW5630HW*"],
        "serial_ranges": [{"scope": "all"}],
    },
}

TSP_W11395614 = {
    "temporal": {"publication_date": "2019-10"},
    "applicability": {
        "models": ["WFW3090GW2", "WFW3090JW0", "WFW5090JW0"],
        "serial_ranges": [
            {"model": "WFW3090GW2", "start": "CF81500000", "end": "CF84510000"},
            {"model": "WFW3090JW0", "start": "CF90830000", "end": "CF90840000"},
        ],
    },
}


def test_bulletin_applies_to_the_anchor_model():
    """W11375982 covers WFW5620HW at all serial numbers."""
    result = document_applies(TSP_W11375982, Appliance(model="WFW5620HW0"))
    assert result.applies
    assert "all serial numbers" in result.reason


def test_out_of_family_bulletin_does_not_apply_to_the_anchor_model():
    """The core negative case: relevant-sounding, wrong appliance."""
    result = document_applies(TSP_W11395614, Appliance(model="WFW5620HW0"))
    assert not result.applies
    assert "not in the document's model list" in result.reason


def test_serial_inside_and_outside_the_documented_range():
    inside = Appliance(model="WFW3090GW2", serial="CF83000000", model_introduced=2018)
    outside = Appliance(model="WFW3090GW2", serial="CF84900000", model_introduced=2018)

    assert document_applies(TSP_W11395614, inside).applies
    assert not document_applies(TSP_W11395614, outside).applies


def test_per_model_serial_ranges_do_not_leak_between_models():
    """WFW3090JW0's range must not be tested against WFW3090GW2's serial."""
    appliance = Appliance(model="WFW3090JW0", serial="CF83000000", model_introduced=2018)
    # CF83000000 sits inside the GW2 range but outside the JW0 range.
    assert not document_applies(TSP_W11395614, appliance).applies


def test_missing_serial_on_a_serial_restricted_document_abstains():
    """Refusing to guess is the correct behaviour, and must be explained."""
    result = document_applies(TSP_W11395614, Appliance(model="WFW3090GW2"))
    assert not result.applies
    assert "no serial number was supplied" in result.reason
