# 02 — Deployment

Default layout: app and local BGE embeddings on your workstation; Postgres on a
LAN Docker host. Langfuse (if used) is a separate Compose stack — not the repair DB.

## Default topology

```mermaid
flowchart LR
  subgraph workstation [Workstation]
    cli[CLI]
    api[FastAPI_plus_UI]
    bge[Local_BGE_embedder]
    env[.env.local]
  end
  subgraph lanHost [LAN_Docker_host]
    compose[docker_compose]
    pg[(Postgres_pgvector)]
  end
  subgraph lfStack [Langfuse_Compose_separate]
    lf[Langfuse_UI]
    lfdb[(Langfuse_own_DB)]
  end

  env --> api
  env --> cli
  cli --> pg
  api --> pg
  api --> bge
  cli --> bge
  compose --> pg
  api -.-> lf
  lf --> lfdb
```

- **Default:** `python -m repair_assistant.api.main` on the laptop; DB at `LAN_HOST:HOST_PORT` ([Deployment](../DEPLOYMENT.md), [ADR-0006](../adr/0006-lan-docker-host.md)).
- **Secrets:** Addresses and passwords live in gitignored `.env.local` / `INFRASTRUCTURE.local.md` — never in Compose committed defaults.
- **Constraint D8:** LAN-only; not internet-facing ([Charter](../CHARTER.md)).

## Optional API container

Same routes and shared DB; useful when you want the API always on the host.

```mermaid
flowchart LR
  laptop[Workstation_CLI_or_browser]
  subgraph lanHost [LAN_Docker_host]
    apiC[Compose_api_service]
    pg[(Postgres_pgvector)]
  end
  laptop --> apiC
  apiC --> pg
```

- **Compose:** `docker/compose.yaml` `api` service builds `docker/Dockerfile` ([ADR-0016](../adr/0016-http-api-docker.md)).
- **Embedder:** Still local BGE inside the API process (shared warmup, pool, session TTL — [ADR-0021](../adr/0021-api-hardening-embedder-sessions.md)).

## Runtime concerns on the API box

```mermaid
flowchart TB
  req[HTTP_request]
  key[Optional_API_key]
  pool[DB_connection_pool]
  sess[In_memory_SessionStore]
  bge[Shared_BGE_warmup]
  handler[ask_or_diagnose]

  req --> key
  key --> handler
  handler --> pool
  handler --> sess
  handler --> bge
```

| Concern | Behavior |
| --- | --- |
| DB pool | Sized / timed out via `REPAIR_DB_POOL_*`; 503 when exhausted |
| Diagnose sessions | In-memory; TTL + max sessions; not durable across restart |
| Streaming cancel | Client disconnect stops the generator (frees LLM/pool work) |
| Langfuse | Own stack — **never** point it at the repair `pgvector` DB ([LANGFUSE](../LANGFUSE.md)) |

**Ops docs:** [INFRASTRUCTURE](../INFRASTRUCTURE.md) · `docker/compose.yaml` · `.env.example`
