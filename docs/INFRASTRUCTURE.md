# Infrastructure

Where this project runs services that are not on the developer workstation.

## Policy

- Docker services for this project (Postgres + pgvector first) run on a **shared
  LAN Docker host**, not on the laptop by default. See ADR-0006.
- **Host addresses, host ports, credentials, and other machines' container
  inventories are local secrets.** They are not committed.
- Tracked docs describe *how* to configure the host. The *values* live in a
  gitignored file next to this one.

## Local file (not in git)

Copy the example and fill in real values:

```text
docs/INFRASTRUCTURE.local.md.example  →  docs/INFRASTRUCTURE.local.md
```

`docs/INFRASTRUCTURE.local.md` is listed in `.gitignore`. So are `.env` /
`.env.local` for connection strings when Compose arrives.

## What belongs where

| In git (this file, ADRs, Compose templates) | Local only (`INFRASTRUCTURE.local.md`, `.env*`) |
| --- | --- |
| Decision to use a LAN Docker host | Host IP / hostname |
| Prefer `pgvector/pgvector:pg17` | Host port mapped to 5432 |
| Prefer a dedicated container/DB for this project | User, password, database name |
| Do not share another project's Postgres | Inventory of other containers on that host |
| Example URL shape with placeholders | Real connection URI |

## Connection string shape (placeholders only)

```text
postgresql://USER:PASSWORD@DOCKER_HOST:HOST_PORT/repair_assistant
```

Resolve `DOCKER_HOST` and `HOST_PORT` from `docs/INFRASTRUCTURE.local.md` (or
from environment variables loaded from `.env.local`).

## Compose (Phase 3)

Template: [`docker/compose.yaml`](../docker/compose.yaml). Env: copy
[`.env.example`](../.env.example) → `.env.local`.

```bash
# From the repo root, with DOCKER_HOST aimed at the LAN Docker daemon if needed:
docker compose --env-file .env.local -f docker/compose.yaml up -d

repair-corpus db-migrate
repair-corpus ingest --all --skip-embed   # schema smoke, no encoder
repair-corpus ingest --all                # local BAAI/bge-base-en-v1.5 (ADR-0009)
```

Container name: `ai-repair-assistant-pg`. Image: `pgvector/pgvector:pg17`.
See ADR-0008 / ADR-0009 for schema and embedding rules.
