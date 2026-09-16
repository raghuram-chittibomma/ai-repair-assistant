# Architecture diagrams

Focused views of the repair assistant — not one mega-diagram. Each page has
multiple Mermaid figures plus short captions and ADR links.

| Diagram | Level | What it shows |
| --- | --- | --- |
| [01 — System context](01-system-context.md) | Context | Actors, surfaces, shared cores, copyright split |
| [02 — Deployment](02-deployment.md) | Deploy | Workstation ↔ LAN Postgres; optional API; runtime pools/sessions; separate Langfuse |
| [03 — Offline ingest](03-offline-ingest.md) | Offline | Manifest → hybrid parse (page router) → contextual chunk + quality repair → embed; opt-in semantic curator |
| [04 — Retrieval](04-retrieval.md) | Shared | Plan → fetch arms → applicability → boosts → owner preference → same-problem coalesce; semantic unit collapse |
| [05 — Ask vs diagnose](05-runtime-ask-diagnose.md) | Runtime | Ask one-shot path vs LangGraph diagnose nodes + session; hybrid PDF evidence on semantic cites |
| [06 — Safety](06-safety.md) | Safety | Pre/post gates, audience rules, owner hard stops (G1–G3) |
| [07 — Observability](07-observability-improve.md) | Improve | Span tree → mine-traces classify → human promote |
| [08 — Semantic curator → generate](08-semantic-curator-to-generate.md) | End-to-end | Opt-in LLM page markers → human PDF board → activate → retrieve reps → generate with layout |

**Also see:** [Charter](../CHARTER.md) · [Deployment](../DEPLOYMENT.md) · [Langfuse](../LANGFUSE.md) · [ADRs](../adr/README.md) · [Evals](../EVALS.md)

The README [Capabilities](../../README.md#capabilities-by-pipeline-layer) section keeps a one-line pipeline overview; these pages are the drill-down. Screenshots of `/ui/corpus` live in the README [Corpus review](../../README.md#corpus-review--semantic-markers) section.
