# ADR-0017: LAN web UI, deployment script, and candidate eval bench

## Status

Accepted

## Context

Phase 9 delivered the HTTP API (ADR-0016). Operators on the LAN needed:

1. A documented path to deploy the API on the shared Docker host (`.52`).
2. A simple web UI — no separate frontend build chain.
3. Expanded eval coverage beyond five smoke scenarios, using
   `evals/scenarios/candidates.yaml` (23+ ready cases).

Deployment remains **LAN-only** (D8). SSH to the Docker host is not assumed;
scripts run on the host via RDP/local shell.

## Decision

1. **`docs/DEPLOYMENT.md` + `docker/deploy-api.ps1`:** build and run
   `ai-repair-assistant-api` on the LAN host, connecting to existing Postgres
   via `host.docker.internal:HOST_PORT`.
2. **Web UI:** single-page app at `/ui` (static HTML/JS served by FastAPI);
   `/` redirects to `/ui`. Calls same-origin `/v1/ask` and `/v1/diagnose`.
3. **Candidate bench:** `repair-corpus bench-candidates` runs live `ask()` on
   all `status: ready` scenarios with a question; grading rules in
   `evals/qa/candidates-grading.yaml` overlay machine-checkable fields.
4. **Shared grader:** `src/repair_assistant/eval/grading.py` used by smoke and
   candidate benches (`must_cite`, `fails_if_contains`, etc.).
5. **`DiagnosticSession.send(db, …)`:** DB passed per turn so HTTP sessions work
   without holding connections.

## Consequences

- First API deploy on the host requires a repo checkout and `.env.local` with
  `OPENAI_API_KEY`.
- Candidate bench is live-only (OpenAI cost); CI covers grader + loader tests.
- Web UI is functional, not polished — sufficient for LAN technician use.
- Prose `fails_if` in candidates.yaml remains human-facing; overlays must be
  updated when new deterministic rules are needed.
