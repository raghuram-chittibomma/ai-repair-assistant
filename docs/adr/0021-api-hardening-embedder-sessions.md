# ADR-0021 — API embedder singleton and in-memory session policy

- Status: Accepted
- Date: 2026-08-26
- Charter: Phase 10 — Product Hardening
- Decisions: 1A (in-memory sessions + TTL/max), 2A (API on laptop / Postgres on LAN)

## Context

The LAN product (ADR-0016/0017) worked but felt unreliable: each ask/search
could reload BGE (~30–60s), diagnose sessions grew without bound and vanished
silently on restart, and each API request opened a fresh Postgres connection.

## Options

| Topic | Options | Choice |
| --- | --- | --- |
| Embedder | Per-request `LocalEmbedder` vs process singleton + warmup | **Singleton + optional startup warmup** |
| Diagnose sessions | Persist in Postgres vs in-memory + TTL/max | **In-memory + TTL/max** (1A); unknown id → HTTP 410 |
| API host | Always-on LAN Docker API vs laptop API | **Laptop API** remains default (2A) |
| DB access | One connection per request vs small pool | **Small pool** (`REPAIR_DB_POOL_SIZE`, default 4) |

| Consequences

- Second ask after process start should not reload sentence-transformers.
- Diagnose chat does **not** survive API restart; UI must handle 410 / New chat.
- Env knobs: `REPAIR_SESSION_TTL_SECONDS` (default 3600), `REPAIR_SESSION_MAX`
  (default 32), `REPAIR_DB_POOL_SIZE`, `REPAIR_DB_POOL_TIMEOUT_SECONDS`
  (default 30; wait then `PoolTimeoutError` → HTTP 503),
  `LLM_TIMEOUT_SECONDS` (default 120; OpenAI → `LLMTimeoutError` → HTTP 504),
  `REPAIR_SKIP_EMBEDDER_WARMUP=1` for tests.
- Postgres session durability remains deferred (single-user LAN; multi-user
  later). Operators use New chat after API restart (HTTP 410).

## Timeouts (Phase 10 reliability)

Hung OpenAI or unbounded pool waits freeze the laptop UI for a single operator.
Bound both:

1. **LLM** — `OpenAI(..., timeout=LLM_TIMEOUT_SECONDS)` on complete and stream;
   map `APITimeoutError` → `LLMTimeoutError` → HTTP **504** (SSE `error` event
   on stream routes).
2. **DB pool** — `queue.get(timeout=REPAIR_DB_POOL_TIMEOUT_SECONDS)` after the
   pool is at capacity; raise `PoolTimeoutError` → HTTP **503**.

Single-user for the near future: do not add multi-tenant session durability or
shared-API fairness in this ADR.

## Follow-on (UI streaming)

Ask mode uses `POST /v1/ask/stream` (SSE). Diagnostic chat uses
`POST /v1/diagnose/stream` (SSE) with the same status/token/done event shape;
`done` also includes `session_id` and `turn`. Search-only mode and chat export
live in `/ui` without changing the non-streaming `/v1/ask` or `/v1/diagnose`
contracts.
