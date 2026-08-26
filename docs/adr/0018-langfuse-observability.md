# ADR-0018: Langfuse for Phase 9 observability

## Status

Accepted

## Context

Charter Phase 9 requires maturing evaluation and introducing **open-source**
tracing/observability after comparing options. ADR-0015 delivered manual Q&A
benches and JSON run logs, and deferred “LangSmith or other trace exporters.”

Constraints for this project:

- **Open source and free** for core use (operator preference).
- **LAN-only (D8)** — no requirement to send traces to a public SaaS.
- App runs on the workstation; Postgres is on the LAN Docker host.
- Eval benches remain **manual** ([EVALS.md](../EVALS.md)).

### Options considered

| | Langfuse | LangSmith |
| --- | --- | --- |
| License | MIT core (self-host free) | Proprietary |
| Self-host | Docker Compose; data on-prem | Enterprise add-on only |
| D8 / LAN | Fits (local host, no cloud required) | Cloud-first; beacon egress if self-hosted |
| LangChain/LangGraph | Official Python SDK | Native (strongest) |
| Cost | Infra only | SaaS tiers or paid Enterprise |

## Decision

1. **Adopt Langfuse (self-hosted OSS)** as the Phase 9 observability platform.
2. **Default deploy:** laptop Docker (`http://localhost:3000`). Do **not** merge
   Langfuse’s stack into [`docker/compose.yaml`](../../docker/compose.yaml)
   (ClickHouse, Redis, MinIO, separate Postgres). Document upstream Compose in
   [LANGFUSE.md](../LANGFUSE.md). LAN-host deploy is a later optional path.
3. **Opt-in SDK instrumentation** for `ask()` and `diagnose` turns when
   `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set; no-op otherwise.
4. **Do not adopt LangSmith.** ADR-0015’s deferred LangSmith exporter is closed
   by this decision.
5. **Keep** ADR-0015 JSON scorecards/run logs and manual benches. Langfuse does
   not replace them and is not required to run benches.

**Charter alignment:** implements Phase 9 observability with an OSS tool.
No new charter deviation.

## Consequences

- Operators who want traces run Langfuse locally and paste keys into `.env.local`.
- Extra containers on the laptop (memory/disk); optional — empty keys = no change.
- Traces may include repair questions and retrieved excerpts — keep Langfuse
  LAN-only and treat keys as secrets.
- Follow-ons (not this ADR): Langfuse on `.52`, auto-scoring benches into
  Langfuse datasets, UI feedback → eval fixtures, LLM-as-judge.

## Follow-on (end-to-end traces)

Nested Langfuse spans now cover retrieval audit (`retrieval`), evidence prompt
(`evidence`), LLM I/O (`llm` generation), and safety gate (`safety_gate`). See
[LANGFUSE.md](../LANGFUSE.md).
