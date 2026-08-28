# ADR-0023: Trace-driven eval mining (Phase 11)

## Status

Accepted

## Context

Phase 9 delivered Langfuse tracing (ADR-0018) and bench-run `promote-eval`
(ADR-0019). Charter Phase 11 requires connecting **live** ask/diagnose failures
back into a reviewable improvement loop without auto-merging gates. Ad-hoc UI
debugging already produced mid-cycle and door-lock fixes; operators need a
repeatable offline loop that does not re-open bugs fixed after the original
traces, and does not silently mutate the eval corpus.

## Decision

1. **CLI `mine-traces`** (manual, offline) fetches Langfuse `ask` / `diagnose`
   traces, classifies failure modes with **rules first**, **replays** each
   candidate on current code/DB, and with `--write` emits a **single analysis
   report** (`evals/qa/drafts/mine-report-*.md`). Suggested fixture YAML may
   appear **inside** that report for copy-paste. Humans alone edit
   smoke/candidates; never auto-set `status: ready`.
2. **No other durable side effects:** no draft YAML files on disk, no
   `mine-state.json`, no append-only improvement log, no edits to live fixtures
   or prompts. Without `--write`, output is terminal-only.
3. **Stale-trace control (all three required):**
   - **Stamp:** every root observation metadata includes `app_git_sha` and
     `app_started_at`.
   - **Window:** default `--since 7d`; skip unstamped traces unless
     `--include-unstamped`; optional `--since-sha`.
   - **Replay gate:** re-run the question on current `ask`. If it now passes
     light deterministic checks, mark `resolved_stale` in the report (no
     action). Only still-failing items are **actionable**.
4. **Dedupe (within a run + ready fixtures):** fingerprint =
   `failure_code` + normalized question; skip duplicates in the same run; mark
   **covered** when a ready smoke/candidate already matches the question
   (read-only check).
5. **Non-goals:** auto-edit prompts; online self-rewrite on the ask path;
   CI-required Langfuse; GraphRAG.

## Consequences

- Pre-fix traces cannot re-open fixed failure modes when replayed on current
  code (the decisive gate).
- Operators review one markdown file and take actions only if they choose —
  same human-in-the-loop discipline as ADR-0019.
- Mining needs `LANGFUSE_*` plus DB + OpenAI when replay is on (default).

## Alternatives considered

- Time window only: rejected — long windows still surface fixed bugs.
- SHA filter only: rejected — same SHA can include later prompt fixes without
  a new process restart; replay remains necessary.
- Auto-write draft YAML + mine-state: rejected — operators want analysis-only
  artifacts; fixture promotion stays fully manual.
- Auto-promote to ready: rejected (ADR-0019).
