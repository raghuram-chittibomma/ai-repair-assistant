# ADR-0026 — Incremental safety gate on the streaming path

- Status: Proposed
- Date: 2026-08-29
- Charter: Phase 8 — safety and escalation (ADR-0014 enforcement)
- Responds to: [ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) **R1**
  (Critical), triaged in slice 1 of
  [ARCHITECTURE_REVIEW_RESPONSE.md](../ARCHITECTURE_REVIEW_RESPONSE.md)

## Context

ADR-0014 decision 4 claims the deterministic gate enforces policy "even if the
model oversteps." That claim held on `/v1/ask` and did **not** hold on the
streaming routes that the web UI actually uses.

`ask_stream` yielded `{"type": "token"}` for every delta as it arrived and ran
`gate_answer` only after the loop finished; `diagnose_turn_stream` had the same
shape. The browser wrote each token straight into the DOM. So an owner asking a
live-voltage question saw the full technician walkthrough render token by token
and then watched it be replaced by an escalation notice. The content had already
been delivered — to the DOM, to any screen recording, to any network capture.

The safety architecture's central claim was false on the default path. This is a
defect at any scale and independent of deployment posture, so it is fixed rather
than deferred.

## Options

| Option | Mechanism | Verdict |
| --- | --- | --- |
| **A** Pre-generation refusal only | Classify before generating; refuse to stream for `escalate` / `block` assessments | **Insufficient alone.** The output guards (`output-bypass`, owner TEST walkthroughs) trip on answers whose *request* assessed as `allow` — that is the whole point of a post-LLM gate. Adopted as one layer, not as the fix |
| **B** Buffer everything, reveal at the end | Stream into a hidden buffer; emit gated text on the terminal event | **Rejected as the default.** Zero leak, but it is non-streaming with extra steps: no progressive reveal, so the perceived-latency benefit the streaming routes exist for is gone |
| **C** Incremental gating (**chosen**) | Accumulate deltas, run the hazard guards over the whole accumulation, release only cleared text behind a hold-back window | **Chosen.** Keeps progressive reveal while making a checkable guarantee |
| **D** Gate the client instead | Have the browser withhold rendering | **Rejected.** Moves a safety control to the untrusted side of the boundary; any other client bypasses it |

C plus A as defence in depth.

## Decision

`safety/stream_gate.py` provides two things, used by both `ask_stream` and
`diagnose_turn_stream`:

1. **`may_stream(assessment)`** — no tokens at all when the outcome is already
   decided (`BLOCK`, or owner + `ESCALATE`). `gate_answer` replaces those answers
   wholesale, so streaming the draft could only show text guaranteed to be
   withdrawn.
2. **`StreamGate`** — accumulates deltas, runs the hazard guards over everything
   accumulated so far, and releases only up to a natural boundary, holding back
   `MAX_HAZARD_MATCH_CHARS` (320) of tail. Once a guard trips, release stops
   permanently, but deltas keep being consumed so the complete draft is still
   available to the authoritative final `gate_answer` and to tracing.

Hazard detection moved into `policy.output_hazard`, now the single definition
shared by `gate_answer` and `StreamGate`. Two copies would drift, and the drift
would be silent in the direction that matters.

### The guarantee

> No complete hazard-pattern match is ever released to the client.

It holds because the guards run over the whole accumulation before any of it is
released, and release stops permanently on a trip. A match wholly inside
already-released text would have tripped an earlier check. A match that completes
later stops the stream before its final characters go out.

### What is deliberately not enforced incrementally

The grounding check (G3, `needs_grounding_citation`) is **not** monotone in the
answer text: a procedure with no citation yet may cite before it ends. Enforcing
it per-delta would abort well-formed answers mid-sentence. It stays a whole-answer
decision in `gate_answer`, whose result is authoritative and which the client
applies on the terminal event.

## Consequences

- Token events no longer map one-to-one onto model deltas. Two existing tests
  asserted that mapping and were updated to assert the contract that matters —
  delivered text equals generated text — since one-delta-one-event is exactly the
  property R1 says must be given up.
- **Short answers barely stream.** With a 320-character hold-back, an answer
  shorter than that arrives in a single event at the end. This is the real cost of
  option C, and it is accepted: the hold-back has to cover the longest hazard span
  or the guarantee weakens to complete-phrase-only, which would let `multimeter`
  reach the client while suppressing only `120 VAC`. The safety fixtures forbid
  the components, not just the full phrase.
- **Residual, stated honestly:** a *prefix* of a hazard phrase whose remainder
  never arrives can still be released — "disconnect the" with nothing after it.
  That is not the hazard, and the hold-back bounds it, but it is not zero.
- Buffered diagnose turns (acknowledgement follow-ups) now emit no token events at
  all. They previously emitted the entire ungated draft as one token immediately
  before the terminal payload, which was the same defect in a second place.
- ADR-0014's decision 4 becomes true on the streaming path. This ADR does not
  supersede ADR-0014; it records the enforcement mechanism that claim requires.
- `MAX_HAZARD_MATCH_CHARS` must be revisited if any hazard pattern in
  `policy.py` grows a wider `.{0,N}` gap. The constant is defined next to those
  patterns for that reason.

## Verification

`tests/test_stream_safety_gate.py` implements the review's acceptance criterion:
drive `ask_stream` with a stub emitting a known-unsafe procedural answer for an
`owner` audience and assert no `token` event contains the forbidden substrings
from `evals/safety/fixtures.yaml`. Cases cover the owner TEST overstep, interlock
bypass output for a technician, owner + escalate emitting nothing, the invariant
across four hold-back sizes, and a long safe answer still arriving in several
parts.
