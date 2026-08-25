"""Deciding whether a manufacturer document applies to a specific appliance.

A repair instruction can be technically correct and still be wrong for the user's
machine. This module implements the deterministic part of that judgement: model
matching, Whirlpool serial-number decoding, and serial-range containment.

Everything here is pure and testable. No model should ever be asked to decide
whether a serial number falls inside a documented range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Model matching
# ---------------------------------------------------------------------------

# Whirlpool model numbers decompose into a base model plus a trailing
# "engineering digit" -- their term, used verbatim in service pointers, which
# write models as e.g. "WTW4816FW*" with the footnote "*denotes engineering
# digit". WFW5620HW0 is base model WFW5620HW, engineering digit 0.
#
# In the manifest, '*' is a suffix wildcard matching zero or more characters.
# That covers both manufacturer usage ("WFW5620HW*" = every engineering digit of
# that base model) and the broader family patterns needed for generic knowledge
# base articles ("WFW*" = any front-load washer model).

_MODEL_TOKEN = re.compile(r"^[0-9A-Z]+\*?$")


def normalise_model(model: str) -> str:
    """Uppercase and strip a model string. Raises on obviously invalid input."""
    cleaned = model.strip().upper()
    if not cleaned:
        raise ValueError("model must not be empty")
    return cleaned


def model_matches(pattern: str, model: str) -> bool:
    """True if ``model`` falls under the manifest ``pattern``.

    >>> model_matches("WFW5620HW*", "WFW5620HW0")
    True
    >>> model_matches("WFW5620HW*", "WFW5622HW0")   # different base model
    False
    >>> model_matches("WFW5620HW0", "WFW5620HW3")   # exact patterns are exact
    False
    """
    pattern = normalise_model(pattern)
    model = normalise_model(model)
    if not _MODEL_TOKEN.match(pattern):
        raise ValueError(f"malformed model pattern: {pattern!r}")

    if pattern.endswith("*"):
        return model.startswith(pattern[:-1])
    return model == pattern


def base_model(model: str) -> str:
    """Strip a single trailing engineering digit, if present.

    Only a trailing *digit* is stripped. Model numbers legitimately end in
    letters denoting colour (WFW5620H**W** = white), and removing those would
    conflate genuinely different models.
    """
    model = normalise_model(model)
    if len(model) > 1 and model[-1].isdigit():
        return model[:-1]
    return model


def engineering_digit(model: str) -> str | None:
    """Return the trailing engineering digit, or None if the model omits it."""
    model = normalise_model(model)
    if len(model) > 1 and model[-1].isdigit():
        return model[-1]
    return None


# ---------------------------------------------------------------------------
# Serial numbers
# ---------------------------------------------------------------------------

# Whirlpool serial layout:
#
#     C      F      8      15     00000
#     |      |      |      |      |
#     |      |      |      |      +-- production sequence that week
#     |      |      |      +--------- week of year, 2 digits
#     |      |      +---------------- year code, 1 character
#     |      +----------------------- optional second division letter, used
#     |                               "for products not built by Whirlpool"
#     +------------------------------ manufacturing division / plant
#
# Verified against four genuine serial ranges quoted in real service pointers:
#   CF81500000 (div CF, 2018 wk 15), CX10xxxx (div C, 2020 wk 10),
#   CC01xxxxx  (div C, 2023 wk 01),  CD05xxxxx (div C, 2024 wk 05).

# Year codes run on a 30-year cycle, so a code alone is ambiguous about the
# decade. 'X' means both 1990 and 2020; 'C' means both 1993 and 2023. Resolving
# a serial to a single year REQUIRES outside context -- normally the year the
# model was introduced. This ambiguity is real and is surfaced, not hidden.
_YEAR_CYCLE = "XABCDEFGHJKLMPRSTUWY0123456789"
_CYCLE_START = 1990
_CYCLE_LENGTH = len(_YEAR_CYCLE)  # 30

assert _CYCLE_LENGTH == 30, "year code cycle must be 30 long"

def year_code_for(year: int) -> str:
    """The Whirlpool year code for a calendar year."""
    if year < _CYCLE_START:
        raise ValueError(f"year {year} predates the documented code cycle")
    return _YEAR_CYCLE[(year - _CYCLE_START) % _CYCLE_LENGTH]


def years_for_code(code: str, horizon: int = 2049) -> list[int]:
    """Every calendar year a code could denote. Usually two candidates."""
    code = code.upper()
    if code not in _YEAR_CYCLE:
        raise ValueError(f"{code!r} is not a valid Whirlpool year code")
    offset = _YEAR_CYCLE.index(code)
    return [y for y in range(_CYCLE_START + offset, horizon + 1, _CYCLE_LENGTH)]


class SerialFormatError(ValueError):
    """Raised when a string is not a recognisable Whirlpool serial number."""


@dataclass(frozen=True)
class Serial:
    """A parsed Whirlpool serial number.

    ``year`` is deliberately absent. A serial does not determine its own year;
    see :meth:`possible_years` and :meth:`resolve_year`.
    """

    raw: str
    division: str
    year_code: str
    week: int
    sequence: str

    @classmethod
    def parse(cls, value: str) -> Serial:
        """Parse a serial, resolving the one- versus two-letter division prefix.

        The division prefix is normally one letter, but Whirlpool documents that
        "for products not built by Whirlpool, an additional alpha is used after
        the first alpha to indicate the source" -- hence prefixes like ``CF``.
        The split is genuinely ambiguous from the characters alone: ``CX090000``
        is division C, year X, week 09, while ``CF81500000`` is division CF,
        year 8, week 15. Both parse structurally under either split.

        The week number disambiguates: only one split yields a week in 1..53.
        A one-letter division is tried first, since it is the documented norm.
        """
        cleaned = value.strip().upper().replace(" ", "")

        attempts: list[str] = []
        for prefix_length in (1, 2):
            match = re.match(
                rf"^(?P<division>[A-Z]{{{prefix_length}}})"
                r"(?P<year_code>[0-9A-Z])"
                r"(?P<week>[0-9]{2})"
                r"(?P<sequence>[0-9xX]{1,6})$",
                cleaned,
            )
            if not match:
                continue
            week = int(match.group("week"))
            if not 1 <= week <= 53:
                attempts.append(f"{prefix_length}-letter division gives week {week}")
                continue
            return cls(
                raw=cleaned,
                division=match.group("division"),
                year_code=match.group("year_code"),
                week=week,
                sequence=match.group("sequence"),
            )

        if attempts:
            raise SerialFormatError(
                f"no valid week in serial {value!r} ({'; '.join(attempts)})"
            )
        raise SerialFormatError(f"not a Whirlpool serial number: {value!r}")

    def possible_years(self, horizon: int = 2049) -> list[int]:
        """All calendar years this serial's year code could mean."""
        return years_for_code(self.year_code, horizon=horizon)

    @property
    def is_ambiguous(self) -> bool:
        """True when the year code maps to more than one plausible year."""
        return len(self.possible_years()) > 1

    def resolve_year(self, reference_year: int) -> int:
        """Pick the most plausible year, given outside context.

        ``reference_year`` is normally the year the model was introduced (the
        8th character of a Whirlpool model number encodes it: 'H' = 2018). An
        appliance cannot have been built before its model existed, so the
        correct reading is the earliest candidate year at or after that point.
        """
        candidates = self.possible_years()
        at_or_after = [y for y in candidates if y >= reference_year]
        if at_or_after:
            return min(at_or_after)
        return max(candidates)

    def _sort_key(self, reference_year: int) -> tuple[int, int, int]:
        """Ordering key. Sequence wildcards ('x') are resolved by the caller."""
        digits = self.sequence.replace("X", "0")
        return (self.resolve_year(reference_year), self.week, int(digits or 0))


def _bound_key(serial: Serial, reference_year: int, *, upper: bool) -> tuple[int, int, int]:
    """Ordering key for a range bound, expanding 'x' placeholders.

    Ranges are quoted with wildcards, e.g. 'CX10xxxx to CX27xxxx'. For a lower
    bound the unknown digits are minimal; for an upper bound, maximal.
    """
    filler = "9" if upper else "0"
    digits = re.sub(r"[xX]", filler, serial.sequence)
    return (serial.resolve_year(reference_year), serial.week, int(digits or 0))


@dataclass(frozen=True)
class SerialRange:
    """An inclusive serial-number range, optionally scoped to one model.

    ``scope_all`` represents the common "All Serial Numbers" case, which is a
    genuine statement of unrestricted applicability rather than missing data.
    """

    start: Serial | None = None
    end: Serial | None = None
    model: str | None = None
    scope_all: bool = False

    @classmethod
    def all_serials(cls, model: str | None = None) -> SerialRange:
        return cls(model=model, scope_all=True)

    @classmethod
    def from_manifest(cls, entry: dict) -> SerialRange:
        if entry.get("scope") == "all":
            return cls.all_serials(entry.get("model"))
        return cls(
            start=Serial.parse(entry["start"]),
            end=Serial.parse(entry["end"]),
            model=entry.get("model"),
        )

    def contains(self, serial: Serial | str, *, reference_year: int) -> bool:
        """Whether a serial falls inside this range.

        ``reference_year`` disambiguates the 30-year year-code cycle and must be
        supplied. There is no sensible default: guessing it silently would
        produce confident, wrong applicability decisions.
        """
        if isinstance(serial, str):
            serial = Serial.parse(serial)
        if self.scope_all:
            return True
        if self.start is None or self.end is None:
            return False

        # A different plant means a different production line. Two serials with
        # matching digits but different division prefixes are unrelated units.
        if serial.division != self.start.division:
            return False

        low = _bound_key(self.start, reference_year, upper=False)
        high = _bound_key(self.end, reference_year, upper=True)
        return low <= serial._sort_key(reference_year) <= high


# ---------------------------------------------------------------------------
# Document-level applicability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Appliance:
    """The appliance a user is asking about.

    ``model_introduced`` is the year the model line was introduced, used to
    disambiguate the 30-year serial year-code cycle. It is optional because the
    user rarely knows it; when it is absent the document's own publication year
    is used instead, which is a sound proxy since a bulletin's serial ranges
    necessarily describe units built around the time it was written.

    Note that Whirlpool model numbers *do* encode an introduction year in their
    8th character ('H' = 2018 for the WFW5620H family), but that letter table is
    NOT the serial year-code table and the two must not be conflated. Only the
    'H' mapping was verified during research, so no general decoder is offered
    here rather than guessing the rest.
    """

    model: str
    serial: str | None = None
    model_introduced: int | None = None


@dataclass(frozen=True)
class ApplicabilityResult:
    applies: bool
    reason: str

    def __bool__(self) -> bool:
        return self.applies


def _publication_year(document: dict) -> int | None:
    raw = (document.get("temporal") or {}).get("publication_date")
    if isinstance(raw, str) and len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def document_applies(document: dict, appliance: Appliance) -> ApplicabilityResult:
    """Whether a manifest document governs a given appliance.

    Returns a reason either way. An unexplained "no" is not reviewable, and the
    reason is what a citation-checking evaluator needs.
    """
    applicability = document.get("applicability", {}) if isinstance(document, dict) else {}

    patterns = applicability.get("models") or []
    matched = [p for p in patterns if model_matches(p, appliance.model)]
    if not matched:
        return ApplicabilityResult(
            False, f"model {appliance.model} is not in the document's model list"
        )

    ranges = [SerialRange.from_manifest(r) for r in applicability.get("serial_ranges") or []]
    if not ranges:
        return ApplicabilityResult(
            True, f"matched model pattern {matched[0]}; no serial restriction stated"
        )

    # A range naming a specific model only constrains that model.
    relevant = [
        r for r in ranges
        if r.model is None or model_matches(r.model, appliance.model)
    ]
    if not relevant:
        return ApplicabilityResult(
            True, f"matched model pattern {matched[0]}; no serial range applies to this model"
        )

    if all(r.scope_all for r in relevant):
        return ApplicabilityResult(True, f"matched model pattern {matched[0]}; all serial numbers")

    if appliance.serial is None:
        return ApplicabilityResult(
            False,
            "document is restricted to specific serial ranges and no serial number was supplied",
        )

    reference_year = appliance.model_introduced or _publication_year(document)
    if reference_year is None:
        return ApplicabilityResult(
            False,
            "serial ranges are stated but the year code cannot be disambiguated: "
            "supply Appliance.model_introduced or a document publication date",
        )

    serial = Serial.parse(appliance.serial)
    for candidate in relevant:
        if candidate.contains(serial, reference_year=reference_year):
            return ApplicabilityResult(True, f"serial {serial.raw} falls within a documented range")

    return ApplicabilityResult(
        False, f"serial {serial.raw} falls outside every documented range for this model"
    )
