# ADR-0034: Diagnose — rules own protocol; LLM owns closed-set understanding

## Status

Accepted — review R18 reading. Does **not** implement R18. Does not change
the production retrieve query builder in [ADR-0013](0013-langgraph-diagnostic.md).

## Context

Diagnose already understands the user with **regex and YAML**, then asks the
LLM to write the next step from whatever chunks came back. Almost everything
that fails mid-session is already a small rule engine:

- Applicability, safety, citation binding, board merge ([ADR-0031](0031-structured-diagnostic-state.md))
- Ack detector in `qa/acks.py`
- Mid-cycle / door polarity in `config/retrieval/query_expand.yaml`
- Diagnose query glue in `diagnostic/graph.py` `_retrieval_query`

The model can already read “stops halfway thru” in prose. It still cites the
wrong chapter (for example Poor Wash) until search does. Groundedness here is
**claims must come from retrieved text**, not **the model may not understand
language**.

Review [R18](../ARCHITECTURE_REVIEW.md) named unconstrained query rewrite.
[ADR-0031](0031-structured-diagnostic-state.md) already rejected a second
planner LLM for the board and kept one structured completion. That is the
right *cost* decision. It is not a decision that “rules should understand the
user.”

A full rule-based diagnose agent would compile the service manual into a
tree. That is the manuals themselves. It still needs NLU on vague first
lines, acknowledgements, and mid-session corrections — more regex, or an
LLM. Replacing generation with a flowchart does not remove hand-picked
mappings; it **is** those mappings for every symptom.

## Options

| | A — Grow synonym regex | B — Rule-only flowchart agent | C — Unconstrained query rewrite | D — Closed-set labels, then OEM family search |
| --- | --- | --- | --- | --- |
| Grounded expansions | No (slang invents search words) | No (every path authored) | No (model invents query text) | Yes (`add_to_search` still OEM) |
| Handles “they look good” then a correction | Brittle | Brittle | Yes, unmeasured | Yes, if labels are curated |
| Extra LLM call | No | No | Maybe | Cheap call **or** earlier use of `diagnostic` — not implemented here |
| Choice | Rejected | Rejected | Rejected (R18 wait) | **Accepted reading; do not start until the owner asks with fixtures** |

## Decision

1. **Do not** replace diagnose with a rule-only expert system.
2. **Do not** grow `query_expand.yaml` as a slang dictionary (`they`,
   `stopping`, `halfway` as the product strategy). The file stays the home
   for *rare OEM expansions*: `when_user_says` is everyday wording;
   `add_to_search` must already appear in the literature.
3. **Do not** implement unconstrained query rewrite (the R18 wait after the
   S5 reject still holds for ranking / free paraphrase).
4. **R18’s honest fix**, when opened, is **closed-set intent** for diagnose
   retrieval: map the utterance to labels that already exist (`ack`,
   `mid_cycle_stop`, `poor_wash`, `error_code`, `unclear`, …). Retrieval
   uses those labels to pick a **family** (for example SDM vs Poor Wash),
   not free paraphrase. Expansion text remains curator YAML.
5. **Rules keep** protocol and evidence: board merge, safety, applicability,
   which OEM phrases may be appended. [ADR-0031](0031-structured-diagnostic-state.md)
   still forbids a second planner LLM for the *board*.
6. **No application code in this ADR.** Measure a later slice against
   `mid-cycle-stop-diag-entry` and the poor-wash fixtures before changing
   `_retrieval_query`.

**Charter:** evidence-driven architecture; no stack deviation. OpenAI stays
LLM-only. No new required cloud dependency.

## Consequences

- Current diagnose still uses `acks.py` and YAML matchers to build the
  search query. That is acknowledged as the wrong NLU slot, not a licence
  to add more synonym rows.
- A later closed-set call is a retrieve-time label, not a board planner, and
  needs its own bench before it ships.
- Ranking work R11 / R20 / R22 remains frozen.
