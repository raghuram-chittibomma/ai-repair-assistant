# Deployment — LAN Docker host

How to run the **API + web UI** on `LAN_HOST` (or your LAN host). **LAN-only**
(D8) — no internet exposure.

## Current state check (from laptop)

```powershell
# Postgres should be open (already running from Phase 3)
Test-NetConnection LAN_HOST -Port 5436

# API — closed until you deploy
Test-NetConnection LAN_HOST -Port 8080
```

## Deploy the API on the host

Remote Docker from the laptop is **not** used. On the **Docker host** (RDP or
local shell):

1. Clone or pull this repo on the host (or copy the checkout).
2. Ensure `.env.local` exists with at least:
   - `POSTGRES_PASSWORD`
   - `OPENAI_API_KEY`
   - `HOST_PORT=5436` (existing Postgres)
   - `API_PORT=8080`
3. Run:

```powershell
cd C:\path\to\ai-repair-assistant
.\docker\deploy-api.ps1
```

This builds the image, connects to Postgres via `host.docker.internal:5436`,
and publishes the API on `8080`.

### Full stack via Compose (fresh host)

If Postgres is **not** running yet:

```powershell
docker compose --env-file .env.local -f docker/compose.yaml up -d --build
```

## Use from the LAN

| URL | Purpose |
| --- | --- |
| `http://LAN_HOST:8080/ui` | Web chat (ask + diagnose) |
| `http://LAN_HOST:8080/health` | Liveness |
| `http://LAN_HOST:8080/ready` | DB connectivity |

No `REPAIR_API_KEY` required (LAN-only).

## Laptop CLI (unchanged)

Point `.env.local` `DATABASE_URL` at `LAN_HOST:5436` and use:

```powershell
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli bench-qa --write
python -m repair_assistant.corpus.cli bench-candidates --write
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `8080` closed | Run `deploy-api.ps1` on the host |
| API `503` on `/ready` | Postgres not running or wrong `DATABASE_URL` |
| First ask very slow | BGE model loading (~30–60s cold start) |
| UI loads but ask fails | Check `OPENAI_API_KEY` in host `.env.local` |
