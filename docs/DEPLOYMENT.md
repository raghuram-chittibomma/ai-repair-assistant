# Deployment

How to run the app day-to-day. **LAN-only** (D8) — not exposed to the internet.

Building or refreshing the Whirlpool **reference** corpus (acquire → parse →
ingest): [REFERENCE_CORPUS_BUILD.md](REFERENCE_CORPUS_BUILD.md).

## Default: app on your machine, Postgres on the LAN host

This is the supported workflow:

| Component | Where it runs |
| --- | --- |
| **Postgres + pgvector** | LAN Docker host (e.g. `LAN_HOST:5436` — see `INFRASTRUCTURE.local.md`) |
| **CLI, API, web UI, BGE embeddings** | Your laptop / workstation |

### 1. Configure `.env.local`

Copy from `.env.example`. Minimum:

```ini
DATABASE_URL=postgresql://repair:YOUR_PASSWORD@LAN_HOST:5436/repair_assistant
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
REPAIR_API_KEY=
```

The API binds **127.0.0.1** by default (`REPAIR_API_HOST`). Leave `REPAIR_API_KEY`
empty on that loopback path. To listen on the LAN, set `REPAIR_API_HOST=0.0.0.0`
deliberately (Compose `api` already does this) and prefer setting `REPAIR_API_KEY`.
The web UI does not send an API key; use `X-API-Key` only from scripts or other
clients.

### 2. Confirm the database is reachable

```powershell
Test-NetConnection LAN_HOST -Port 5436
```

Postgres must already be running on the LAN host (see [INFRASTRUCTURE.md](INFRASTRUCTURE.md)).

### 3. Run the CLI

```powershell
pip install -e ".[dev]"
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli diagnose --model WFW5620HW0
```

### 4. Run the API + web UI (optional)

```powershell
python -m repair_assistant.api.main
```

Open **http://localhost:8080/ui** in your browser.

| URL | Purpose |
| --- | --- |
| `http://localhost:8080/ui` | Web chat (ask stream + diagnose + search) |
| `http://localhost:8080/health` | Liveness |
| `http://localhost:8080/ready` | DB + embedder + session count (Phase 10) |
| `http://localhost:8080/v1/ask` | Non-streaming grounded answer |
| `http://localhost:8080/v1/ask/stream` | SSE streaming ask (UI default) |
| `http://localhost:8080/v1/search` | Retrieval hits only |
| `http://localhost:8080/v1/diagnose` | Multi-turn diagnostic chat (non-streaming) |
| `http://localhost:8080/v1/diagnose/stream` | SSE streaming diagnostic chat (UI default) |

The API on your laptop connects to Postgres on the LAN host via `DATABASE_URL`.

**Phase 10 notes:** the API process keeps a shared BGE embedder (warmed at
startup) and a small Postgres pool with a bounded wait
(`REPAIR_DB_POOL_TIMEOUT_SECONDS`, default 30s → HTTP 503 if exhausted).
OpenAI calls are bounded by `LLM_TIMEOUT_SECONDS` (default 120s → HTTP 504).
Diagnose sessions are **in-memory** (TTL + max cap) — they do not survive API
restart; the UI shows a clear error (HTTP 410) and you start a new chat. See
[ADR-0021](adr/0021-api-hardening-embedder-sessions.md).

### 5. Eval benches (manual)

Live evals are run by hand — see [EVALS.md](EVALS.md) for every level
(parsing, retrieval, safety, Q&A smoke, candidates). Quick check:

```powershell
python -m repair_assistant.corpus.cli bench-safety
python -m repair_assistant.corpus.cli bench-qa --write
python -m repair_assistant.corpus.cli bench-candidates --write
```

Optional live traces (not required for benches): [LANGFUSE.md](LANGFUSE.md).

---

## Troubleshooting (local app)

| Symptom | Fix |
| --- | --- |
| `DATABASE_URL` / connection errors | Check `.env.local`; confirm port 5436 open on LAN host |
| API `503` on `/ready` | Postgres not running on the LAN host |
| First ask/search after process start slow | BGE cold load (~30–60s once per process; later asks reuse the singleton) |
| Ask/diagnose HTTP 504 / “timed out” | OpenAI exceeded `LLM_TIMEOUT_SECONDS` (default 120); retry or raise the limit |
| Ask/diagnose HTTP 503 pool exhausted | Wait briefly and retry; raise `REPAIR_DB_POOL_SIZE` only if needed |
| Diagnose “session expired” after restart | Expected — sessions are in-memory; click **New chat** |
| UI 401 with API key set | Enter the same value in the UI **API key** field (stored in localStorage) |
| UI works but answers fail | Check `OPENAI_API_KEY` in `.env.local` |
| `repair-corpus` not found | Use `python -m repair_assistant.corpus.cli …` |

---

## Optional: run everything on the LAN Docker host

Not required for normal use. Only if you want the API container on the same
machine as Postgres (e.g. always-on box without your laptop).

On the **Docker host** (RDP / local shell), with the repo and `.env.local`:

```powershell
.\docker\deploy-api.ps1
```

Then use `http://<lan-host-ip>:8080/ui` from other machines on the network.

### Fresh host — Postgres + API via Compose

If Postgres is not running yet:

```powershell
docker compose --env-file .env.local -f docker/compose.yaml up -d --build
```

See [INFRASTRUCTURE.md](INFRASTRUCTURE.md) for host/port policy.

The API image runs as a non-root `app` user (uid 1000). `.dockerignore` keeps
`corpus/documents` and `.env.local` out of the build context.

**Embeddings cache (not baked into the image).** `BAAI/bge-base-en-v1.5` is
~400MB; the Dockerfile sets `HF_HOME=/home/app/.cache/huggingface` and
downloads on first use. To run without Hugging Face on the network, copy a
pre-populated cache into that path (or bind-mount your host
`~/.cache/huggingface`) and set `HF_HUB_OFFLINE=1` so `sentence-transformers`
uses local files only.
