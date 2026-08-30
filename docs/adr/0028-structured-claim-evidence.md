# ADR-0028: Claim→evidence binding is structured, not regex-scraped

## Status

Accepted — review R23. Precondition for groundedness measurement (R27).

## Context

[ADR-0012](0012-grounded-qa.md) asks the model to write `[1]`, `[2]` in free
prose. `citations_from_answer` scrapes those markers. A reply that says
"per the service manual" with no `[n]` ships **zero** citations;
`citations_by_label_mention` then guesses by substring. That is not a binding.

Review R23: the claim→evidence link must be a schema field so R27 can score
`(claim, evidence block)` pairs.

Streaming safety ([ADR-0026](0026-streaming-safety-gate.md)) gates **user-facing
prose**. JSON tokens must not reach the client or the incremental gate.

## Options

| | A — Keep regex scrape | B — Structured complete; stream buffers | C — Second bind-only LLM call |
| --- | --- | --- | --- |
| Binding | Inferred | Explicit `evidence_index` | Explicit, extra cost |
| Stream UX | First token early | First token after the full completion | Unchanged stream + extra latency |
| Choice | Rejected | **This ADR** | Rejected (two calls, same schema) |

## Decision

1. Live OpenAI calls use `response_format` `json_schema` (`grounded_answer`):
   `abstained`, `abstain_reason`, `answer`, `claims: [{text, evidence_index}]`.
   `evidence_index` is the 1-based block from `format_evidence`, or null.
2. Citations on `AnswerResult` come from `claims[].evidence_index`, validated
   against the available pool. `[n]` in `answer` is display and a **fallback**
   when the model returns prose (tests, parse failure). Label-theme guessing
   is not used on the ask complete path.
3. The stream path **buffers** the completion, parses, runs `gate_answer` on
   the rendered `answer`, then may emit that prose as token events. Incremental
   gating still applies to user-facing text, not JSON.
4. Diagnose `respond` uses the same parser. Claims sit on graph state so
   `citations_for_turn` does not scrape first.
5. Mock LLMs may still return `ABSTAIN: …` or cited prose; the parser accepts
   those so CI does not need OpenAI.

**Charter:** no deviation. OpenAI remains LLM-only.

## Consequences

- First streamed token arrives after the structured completion finishes.
- `bench-qa` fixtures that only check citation identity still pass; R27 will
  use `claims` for faithfulness.
- A model that omits `claims` but writes `[n]` still binds via the fallback.
  A model that omits both still has zero citations — that is now an empty
  schema, not a silent theme guess.
