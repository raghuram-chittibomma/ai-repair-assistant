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
span with question, retrieval count, citations, safety metadata, and
`app_git_sha` / `app_started_at` stamps (ADR-0023).

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

When keys are set, each `ask` / `ask_stream` / `diagnose` turn produces a **nested
trace** in Langfuse:

```
ask | diagnose
├── safety_assess
├── retrieval          ← chunk pipeline audit
├── evidence           ← numbered evidence block sent to the LLM
├── llm (generation)   ← full messages[] in, model text out
└── safety_gate        ← raw vs gated answer
```

| Span | Fields |
| --- | --- |
| Root (`ask` / `diagnose`) | question/message, model, appliance, abstain, citation labels, duration, `audience` / `audience_verified=false` / `technician_attested` (R2) |
| `retrieval` | query, source counts (vector/code/connector/reference/revision), merged candidates, **selected** chunks (score, apply_reason, preview), **rejected** (applicability), **ranked_before_diversity**, **diversity_dropped** |
| `evidence` | full `evidence_text` prompt block (truncated at `REPAIR_TRACE_MAX_CHARS`, default 12000) |
| `llm` | `messages` array (system + user) in; `content` (full model output) out |
| `safety_assess` | action, rule_id, reason, prompt_directive |
| `safety_gate` | raw preview, blocked, notice, gated text preview |

Long strings are truncated automatically. Override with `REPAIR_TRACE_MAX_CHARS` in
`.env.local` if you need longer prompt captures.

When `bench-qa` / `bench-candidates` run with Langfuse keys set, spans also carry
`eval_bench`, `eval_run_id` (matches the JSON filename stamp), and `scenario_id`
(E11). Interactive `ask` / `diagnose` leave those fields unset.

### Diagnostic sessions in Langfuse

Each **diagnose** turn is still one trace, but turns that share the same app
`session_id` (from `/v1/diagnose` or the CLI) are grouped in Langfuse **Sessions**:

1. Run several turns in **Diagnostic chat** mode (same chat — do not click New chat).
2. In Langfuse, open **Sessions** (or filter traces by `session_id`).
3. Click the session whose id matches the UI pill (`Session …xxxxxxxx`) — all
   turns for that conversation appear together.

Each trace also carries `metadata.diagnose_session_id` for search/filter backup.
Ask mode has no session grouping (one trace per question).

Benches (`bench-qa`, `bench-candidates`, …) do **not** require Langfuse. If keys
are set during a bench run, traces will also be sent (OpenAI cost unchanged).

## Data governance (review R44)

This product is a single-user LAN assistant. Tracing is opt-in. There is no
multi-user privacy program, no subject-access API, and no automatic redaction of
free-text symptoms. The following is the whole available action space.

### What a trace holds

When keys are set, Langfuse receives the question or diagnose message, appliance
model and serial, retrieved evidence excerpts, the LLM prompt and completion, and
safety metadata. Serial numbers are device-identifying; combined with free text
they can edge toward personal data.

Leave `LANGFUSE_*` empty to stop sending new traces. Existing data stays in the
Langfuse volumes until you delete it.

### Redaction

Set `REPAIR_TRACE_REDACT_SERIAL=1` in `.env.local` to replace `serial` /
`appliance_serial` fields and serial-shaped tokens (two letters + 8+ digits, not
`W########` publication numbers) with `[serial]` before a payload is sent.
Questions and symptoms are otherwise stored as typed. Redaction is off by
default so a local debug session can still see the serial the operator typed.

### Retention

Self-hosted Langfuse **keeps event data indefinitely** until a project retention
period is set. In the Langfuse UI: **Project Settings → Data Retention**, number
of days (minimum 3). A nightly job then deletes traces, observations, scores,
and media older than that window. See
[Langfuse data retention](https://langfuse.com/docs/administration/data-retention).
On the laptop Docker Compose stack, retention also needs MinIO/S3 delete
permission (the upstream compose already grants it).

This repo does not set a retention default — that is an operator choice on the
Langfuse project, not an application setting.

### Deletion

| Goal | How |
| --- | --- |
| One trace | Langfuse UI → Traces → open the trace → delete. Irreversible. |
| Time window | Project retention above. Nightly; cannot recover. |
| Everything on this machine | In the Langfuse checkout: `docker compose down -v`. Destroys Postgres, ClickHouse, and MinIO volumes. |
| Stop sending | Clear `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` and restart the app. |

There is no deletion route in this application's API or UI. While the charter is
single-user LAN, adding one would be theatre.
