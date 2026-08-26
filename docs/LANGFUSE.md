# Langfuse (optional tracing)

Self-hosted [Langfuse](https://langfuse.com) (MIT core) for inspecting live
`ask` / `diagnose` / API runs. See [ADR-0018](adr/0018-langfuse-observability.md).

**Not required** for CLI, UI, or [manual eval benches](EVALS.md). Leave
`LANGFUSE_*` keys empty to disable tracing.

## Default: laptop Docker

Langfuse’s stack (web, worker, Postgres, ClickHouse, Redis, MinIO) is separate
from this repo’s [`docker/compose.yaml`](../docker/compose.yaml) (repair Postgres).

### 1. Start Langfuse

```powershell
git clone https://github.com/langfuse/langfuse.git
cd langfuse
# Edit docker-compose.yml secrets marked CHANGEME, then:
docker compose up -d
```

Wait until the web container reports ready (~2–3 minutes). Open
**http://localhost:3000**.

Official guide: [Docker Compose deployment](https://langfuse.com/self-hosting/docker-compose).

Python client: `pip install 'langfuse>=4,<5'` (already in project dependencies).
On Python 3.14+, use Langfuse SDK v4+ (v3 fails on pydantic v1).

### 2. Create a project and keys

In the Langfuse UI: create an organization/project, then create API keys
(public + secret).

### 3. Configure this app

In `.env.local` (see `.env.example`):

```ini
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

### 4. Smoke test

```powershell
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
```

Open the Langfuse UI → Traces. You should see an `ask` (and later `diagnose`)
span with question, retrieval count, citations, and safety metadata.

## Optional: LAN Docker host

Use this when you want Langfuse always on and have spare host RAM (32 GiB is
plenty alongside repair Postgres). App still runs on the laptop.

### On the Docker host (RDP / local shell)

```powershell
git clone https://github.com/langfuse/langfuse.git
cd langfuse
# Edit docker-compose.yml secrets marked CHANGEME, then:
docker compose up -d
```

Confirm port **3000** is free and not exposed past the LAN (D8). Open
`http://<lan-host-ip>:3000` from a browser on the network → sign up → create
project → API keys.

Do **not** point Langfuse at the repair `pgvector` database; use the Postgres
that Langfuse's own Compose starts.

### On the laptop `.env.local`

```ini
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://LAN_HOST:3000
```

(Replace `LAN_HOST` with your host from `INFRASTRUCTURE.local.md`.)

Then smoke-test with `ask` as above; traces appear in the LAN Langfuse UI.

## What is traced

When keys are set:

| Entry | Trace name | Typical fields |
| --- | --- | --- |
| `ask()` | `ask` | question, model, appliance, hit count, abstain, citations, safety |
| `DiagnosticSession.send` | `diagnose` | user message, turn, retrieval count, abstain, safety |

When `bench-qa` / `bench-candidates` run with Langfuse keys set, spans also carry
`eval_bench`, `eval_run_id` (matches the JSON filename stamp), and `scenario_id`
(E11). Interactive `ask` / `diagnose` leave those fields unset.

Benches (`bench-qa`, `bench-candidates`, …) do **not** require Langfuse. If keys
are set during a bench run, traces will also be sent (OpenAI cost unchanged).
