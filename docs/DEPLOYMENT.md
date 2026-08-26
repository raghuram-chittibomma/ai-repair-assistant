# Deployment

How to run the app day-to-day. **LAN-only** (D8) — not exposed to the internet.

## Default: app on your machine, Postgres on the LAN host

This is the supported workflow:

| Component | Where it runs |
| --- | --- |
| **Postgres + pgvector** | LAN Docker host (e.g. `LAN_HOST:5436`) |
| **CLI, API, web UI, BGE embeddings** | Your laptop / workstation |

### 1. Configure `.env.local`

Copy from `.env.example`. Minimum:

```ini
DATABASE_URL=postgresql://repair:YOUR_PASSWORD@LAN_HOST:5436/repair_assistant
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
REPAIR_API_KEY=
```

Leave `REPAIR_API_KEY` empty (LAN-only, no auth needed).

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
| `http://localhost:8080/ui` | Web chat (ask + diagnose) |
| `http://localhost:8080/health` | Liveness |
| `http://localhost:8080/ready` | Database connectivity |

The API on your laptop connects to Postgres on the LAN host via `DATABASE_URL`.

### 5. Eval benches (manual)

Live evals are run by hand — see [EVALS.md](EVALS.md) for every level
(parsing, retrieval, safety, Q&A smoke, candidates). Quick check:

```powershell
python -m repair_assistant.corpus.cli bench-safety
python -m repair_assistant.corpus.cli bench-qa --write
python -m repair_assistant.corpus.cli bench-candidates --write
```

---

## Troubleshooting (local app)

| Symptom | Fix |
| --- | --- |
| `DATABASE_URL` / connection errors | Check `.env.local`; confirm port 5436 open on LAN host |
| API `503` on `/ready` | Postgres not running on the LAN host |
| First ask/search very slow | BGE model loading on your machine (~30–60s cold start) |
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
