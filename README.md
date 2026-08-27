# AI Repair Assistant

Self-hostable **framework** for building a grounded appliance repair assistant:
answers and multi-turn diagnosis over **your** manufacturer documentation, with
citations, model/serial applicability, and safety checks.

This repository was proven with a **Whirlpool front-load washer** reference
corpus (WFW5620H / WFW5620HW0). The app code is reusable; the PDFs and manifest
are the brand-specific layer. To reproduce that reference build, see
[Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md) — not required reading
to understand what the product does.

> **Status: Phase 10 of 11 (hardening).** App on your machine; Postgres on a LAN
> Docker host. Web UI at `http://localhost:8080/ui`
> ([Deployment](docs/DEPLOYMENT.md)). Manual evals ([Evaluation](docs/EVALS.md)).
> Optional [Langfuse](docs/LANGFUSE.md) traces. Phase 11 (trace → draft evals)
> is deferred. **LAN-only** (D8) — not internet-facing.

---

## Capabilities

- **Grounded ask** — one-shot Q&A from retrieved manufacturer chunks, with
  numbered citations; streaming answers in the UI/API
- **Multi-turn diagnose** — session-based troubleshooting (LangGraph) with the
  same citation and applicability rules
- **Hybrid retrieval** — vector + identifier/code/connector paths, ranked with
  authority and applicability filters (wrong model/serial docs stay out)
- **Safety gate** — blocks or escalates unsafe guidance (e.g. live-voltage /
  technician-only procedures) before or after generation
- **Local embeddings** — open-source `BAAI/bge-base-en-v1.5`; OpenAI only for
  LLM generation
- **HTTP API + web UI** — LAN chat for ask and diagnose, search, export, cancel
- **Observability** — optional self-hosted Langfuse traces (retrieval audit, LLM
  I/O, safety spans)
- **Eval harnesses** — parsing, retrieval, QA, safety, chain benches (manual runs)

Applicability and document precedence are first-class in the corpus manifest
([ADR-0004](docs/adr/0004-applicability-and-precedence.md)), not left to
similarity alone.

---

## Use it

Assumes Postgres is up, `.env.local` is configured, and a corpus is already
ingested. Full install and DB layout: [Deployment](docs/DEPLOYMENT.md).

```bash
pip install -e ".[dev]"

# API + UI (same machine)
python -m repair_assistant.api.main
# open http://localhost:8080/ui
```

CLI (Windows-friendly module form):

```powershell
python -m repair_assistant.corpus.cli search "door won't lock" --model WFW5620HW0
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli diagnose --model WFW5620HW0
```

If `repair-corpus` is on your PATH, those commands work without `python -m …`.

**No corpus yet?** Follow [Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md)
(acquire → parse → ingest), then return here.

---

## As a framework

1. Describe documents in `corpus/manifest/` (identity, applicability, precedence).
2. Acquire manufacturer files yourself; store under `corpus/documents/` (gitignored).
3. `parse` → `ingest` → use ask / diagnose / UI.
4. Keep eval fixtures and ADRs as the quality bar when you change chunking or
   retrieval.

Vision and constraints: [Project charter](docs/CHARTER.md).

---

## Documents are not in this repository

Manufacturer manuals and tech sheets are copyrighted and **never** committed
here. The repo ships a **manifest** (what should exist, hashes, applicability)
and tools to verify what you acquired — the same idea as Nixpkgs `requireFile`
or MAME software lists. There is no `fetch` / `download` command.

Details: [Corpus licensing](docs/CORPUS_LICENSING.md).

---

## Repository layout

```
corpus/manifest/         document manifest (committed)
corpus/documents/        acquired PDFs (gitignored, never committed)
docs/adr/                architecture decision records
docs/corpus/             acquisition guide and corpus study
evals/                   evaluation fixtures and scorecards
src/repair_assistant/    application code
tests/                   deterministic tests
```

## Documentation

- [Deployment](docs/DEPLOYMENT.md) — run API/UI/CLI against LAN Postgres
- [Evaluation](docs/EVALS.md) — manual benches at every pipeline layer
- [Project charter](docs/CHARTER.md) — vision, constraints, roadmap
- [Langfuse](docs/LANGFUSE.md) — optional self-hosted tracing
- [Architecture decision records](docs/adr/) — design decisions
- [Infrastructure](docs/INFRASTRUCTURE.md) — LAN Docker / Compose
- [Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md) — Whirlpool acquire → ingest CLI sequence
- [Acquisition guide](docs/corpus/ACQUISITION.md) — per-document obtain notes
- [Corpus licensing](docs/CORPUS_LICENSING.md) — copyright; no downloader
- [Corpus study](docs/corpus/CORPUS_STUDY.md) — what is in the reference docs

## Stack

Python, PostgreSQL, pgvector, Docker, OpenAI, and LangGraph are set in the
[charter](docs/CHARTER.md). Typical layout: Postgres on a **LAN Docker host**;
CLI, API, UI, and BGE embeddings on **your machine**. Embeddings are local
open-source (ADR-0009); OpenAI is for LLM inference only.

## Licence

Application code and project metadata: Apache-2.0. Manufacturer documentation
remains the copyright of its respective owners and is not distributed here.
