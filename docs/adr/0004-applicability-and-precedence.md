# ADR-0004: Applicability and precedence are structured data, not text

- **Status:** Accepted
- **Date:** 2026-08-25
- **Phase:** 1

## Context

A repair instruction can be perfectly correct, well written, and highly relevant
to the question — and still be wrong for the user's machine. This is the failure
mode that distinguishes appliance repair from most retrieval problems, and the
corpus contains real examples of it.

**Applicability.** TSP W11395614 is a Whirlpool front-load washer bulletin about
a door that locks but will not run. For a WFW5620HW0 owner describing exactly
that symptom, it is the most relevant document in the corpus by any similarity
measure. It applies only to 24-inch models within three serial ranges. Citing it
would be a failure.

**Precedence.** TSP W11375982 exists solely to say that service manual
W11169652 is *wrong* at "Test #1: ACU Power Check, Step 10". The manual is
longer, more detailed and more authoritative-looking. The two-page bulletin
wins.

Both facts are stated in the documents in prose. The question is whether to
leave them there.

## What the real documents demand

Applicability turns out to be expressed on **six independent axes**, all observed
in actual Whirlpool documents:

| Axis | Real example |
| --- | --- |
| Base model | 23 base models in W11169652 |
| Engineering digit | W11320547 Rev C covers `WFW5620HW0` only |
| Platform / category | The three F5E2 articles differ only by product category |
| Serial range | `CF81500000`–`CF84510000` in W11395614 |
| Effective dates | 2025-02-12 to 2025-12-31 in W11766193 Rev B |
| Software version | SC.02 versus SC.03 in W11533288 Rev A |

Any one of them can exclude a document that matches on all the others.

Precedence has **four** distinct forms, three of which the manufacturer states
outright rather than leaving to inference:

1. `corrects` — a bulletin invalidates one passage, the rest of the document
   stands. Distinct from supersession, and needs a locator.
2. `superseded_by` within a publication number — Rev A → Rev B.
3. `superseded_by` across publication numbers — W11156985 → W11355369. Invisible
   to revision-letter comparison.
4. Document-type precedence stated in the text — the service manual calls its
   own wiring diagram "typical" and "for training only" and defers to the
   diagram supplied with the product.

## Decision

Model all of it as **first-class manifest fields**, validated by JSON Schema and
resolved by deterministic code in `repair_assistant.corpus.applicability`.

- `applicability` carries `models` (with `*` suffix wildcards), `platform`,
  `product_category`, `serial_ranges`, `effective_dates`, `software_versions`
  and `regions`.
- `relationships` carries typed edges with a `target`, an optional
  `target_revision`, and a `locator` naming where in the target the relationship
  applies.
- `authority.tier` gives a coarse ordering: `bulletin` > `service_literature` >
  `owner_literature` > `support_article`.

Serial-range containment, model matching and year-code decoding are pure
functions with tests. **No language model is ever asked whether a serial number
falls inside a range.**

## Rationale

These are decidable facts. `CF83000000` either falls inside
`CF81500000`–`CF84510000` or it does not, and a function answers that correctly
every time for no cost. Delegating it to a model would introduce a failure mode
where none needs to exist, and the failure would be silent and confident.

Structured fields also make the corpus *testable*. `test_manifest.py` asserts
that all five distractors are excluded for the anchor model and all applicable
documents retained. That assertion is only possible because applicability is
data.

Three implementation details are worth recording, because each was a real
decision:

**Serial year codes are ambiguous and the ambiguity is surfaced.** Whirlpool
year codes run on a 30-year cycle, so `X` means both 1990 and 2020. `Serial` has
no `year` attribute; it has `possible_years()` and `resolve_year(reference)`.
Callers must supply context — the model introduction year, or failing that the
document's publication year. Guessing silently would produce confident, wrong
applicability decisions.

**The division prefix is genuinely ambiguous and is resolved by validation.**
`CF81500000` is division `CF`, year `8`, week `15`; `CX090000` is division `C`,
year `X`, week `09`. Both parse structurally under either split, and only the
week number (which must be 1–53) distinguishes them. The parser tries both.

**Applicability and supersession are deliberately separate.** The old Use & Care
guide W11156985A *does* apply to WFW5620HW0 — it is the wrong document to cite
because something replaced it, not because it does not apply. Conflating the two
would make the distinction untestable, so `document_applies` returns true for it
and the supersession edge handles the rest.

## Consequences

**Good.** Applicability filtering is exact, fast, explainable and testable.
Every decision comes with a human-readable reason, which is what a
citation-checking evaluator needs. Precedence is a graph that can be traversed.

**Bad.** Every field must be transcribed by hand from the documents, which is
slow and error-prone; a mistranscribed serial range is a silent wrong answer.
The schema may not cover applicability forms not yet encountered — a seventh
axis is likely to turn up. `authority.tier` is a coarse ordering and will not
resolve every conflict on its own.

**Deferred to later phases.** Ranking when two applicable documents disagree and
neither declares precedence over the other. Phase 1 records the edges; Phase 5
decides what to do with them.
