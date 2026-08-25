# ADR-0016: Self-hosted HTTP API and Docker deployment

## Status

Accepted

## Context

Phases 1–8 delivered CLI tools, Postgres/pgvector ingestion, retrieval, grounded
Q&A, LangGraph diagnostics, safety policy, and Q&A eval logging. Charter Phase
10 calls for product hardening including APIs, deployment, and operational
visibility. ADR-0013 deferred session persistence and HTTP access.

The LAN Docker host already runs Postgres (ADR-0006). Operators need a stable
HTTP surface for integrations without reimplementing CLI wiring.

## Decision

1. **FastAPI service** at `src/repair_assistant/api/`:
   - `GET /health` — liveness (no auth)
   - `GET /ready` — Postgres connectivity
   - `POST /v1/search`, `/v1/ask`, `/v1/diagnose` — same logic as CLI
   - `DELETE /v1/diagnose/{session_id}` — drop in-memory session
2. **Optional auth (LAN-only):** `REPAIR_API_KEY` env var; when set, routes
   require `X-API-Key`. **Default: empty** — appropriate for LAN-only use
   (charter deviation D8). No TLS, OAuth, or internet-facing hardening is planned.
3. **Diagnose sessions:** in-memory `SessionStore` keyed by UUID; not durable
   across restarts. `DiagnosticSession` refactored to accept `db` per turn so
   HTTP handlers use short-lived connections.
4. **Deployment:** `docker/Dockerfile` + `api` service in `docker/compose.yaml`.
   Manifest ships in the image; corpus PDFs remain off-image. Embeddings model
   downloads on first request (same as CLI).
5. **CLI entry:** `repair-assistant-api` (uvicorn) for non-Docker runs.

**Charter alignment:** implements Phase 10 (README Phase 9). Deployment scope
narrowed to LAN-only ([D8](../CHARTER.md#deviations-from-this-charter)).

**Out of scope:** web UI, internet exposure, TLS/reverse-proxy setup, OAuth,
horizontal session replication, GPU serving.

## Consequences

- API container is large (sentence-transformers + torch). First `/v1/search`
  after cold start may be slow while BGE loads.
- Multi-turn diagnose sessions are lost on API restart; clients should tolerate
  new `session_id` or replay context.
- Compose `DATABASE_URL` for `api` uses the internal `postgres` hostname; laptop
  CLI continues to use LAN host IP from `.env.local`.
