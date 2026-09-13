# ADR-0046: Live diagnose protocol is the current symptom span

## Status

Accepted. Extends [ADR-0045](0045-diagnose-tally-symptom-trail.md). Does
not replace the first `symptom_anchor` or drop trail history. Not R41.

## Context

A corrected problem appends a tally span and searches again. Live
`ruled_out` still held every prior check, so TEST #4 done for “won’t
open” counted as already done for “won’t close.” Close-by-rule, offered
dedupe, generate’s board, and hit demote all treated it as a duplicate.

The trail must keep those checks. Protocol must not.

## Options

| | A — Keep one live `ruled_out` | B — Reset live protocol on a new span | C — Wipe the trail |
| --- | --- | --- | --- |
| Same TEST offerable on the new problem | No | Yes | Yes |
| First-path checks still visible | Yes | Yes | No |
| Choice | Rejected | **Accepted** | Rejected |

## Decision

1. **On `new_symptom` / `mid_cycle_stop`**, freeze the previous
   `ruled_out` onto that span (ADR-0045), then start a fresh live
   `ruled_out` and hypotheses. `next_check` already clears.
2. **Close-by-rule, harvest, offered, generate board, and demote**
   use only the live list — the current problem. History stays on
   `symptom_path` for the tally.
3. **Classify still returns a label only.** No new slang regex.

## Consequences

- TEST #4 (or any on-page check) can be named again after the problem
  changes. The trail still shows it under the first symptom.
- Measure with board/tally unit tests. No retrieval fixture.
