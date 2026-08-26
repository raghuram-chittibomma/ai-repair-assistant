# AI Repair Assistant

An open-source, self-hostable assistant that helps diagnose and troubleshoot household
appliances using authoritative manufacturer documentation, with grounded answers and
traceable citations.

Initial scope is deliberately narrow: **Whirlpool front-load washers, WFW5620H family,
anchor model WFW5620HW0.** The aim is one product family understood deeply rather than
many understood superficially.

> **Status: Phase 10 of 10 (hardening).** Run the app on your machine; Postgres
> lives on the LAN Docker host. CLI, API, and web UI at `http://localhost:8080/ui`
> (see [Deployment](docs/DEPLOYMENT.md)). Eval harnesses at every layer — **manual
> runs** only ([Evaluation](docs/EVALS.md)). Optional self-hosted **Langfuse**
> traces ([LANGFUSE.md](docs/LANGFUSE.md), ADR-0018). **LAN-only** (D8) — not
> internet-facing.

---

## The one thing to understand first

**This repository contains no manufacturer documents, and never will.**

Whirlpool service manuals, tech sheets, and service pointers are copyrighted. This project
commits a *manifest* that describes each document — publication number, revision, model
applicability, serial ranges, source, and cryptographic hash — and ships a tool that tells
you what is missing and verifies what you have. You acquire the documents yourself.

This follows the same pattern as Nixpkgs `requireFile` and MAME's software lists. See
[docs/CORPUS_LICENSING.md](docs/CORPUS_LICENSING.md) for the full reasoning, including why
the project ships no downloader.

---

## Quick start

```bash
pip install -e ".[dev]"
git config core.hooksPath .githooks   # refuses to commit document artefacts

repair-corpus status                  # what the corpus needs and what you have
```

On a fresh clone every document will be reported as missing, with instructions:

```
missing   service_manual            W11169652 Rev A   27in Front-Load Washers (L-97)
          how to obtain: oem_public_pdf
          https://www.whirlpool.com/content/dam/global/documents/201905/...
          save as: corpus/documents/W11169652A.pdf
```

Download them wherever your browser puts them, then let the tool sort them out —
it identifies each file by its publication number and renames it correctly:

```bash
repair-corpus intake ~/Downloads/whirlpool   # dry run
repair-corpus intake ~/Downloads/whirlpool --apply

repair-corpus verify                  # hash and check against the manifest
repair-corpus pin --write             # record hashes for newly acquired files
repair-corpus show W11375982          # full metadata for one document
repair-corpus applies --model WFW5620HW0

repair-corpus bench-parse             # re-score extractors against parsing fixtures
repair-corpus parse tech-sheet-w11320651
repair-corpus parse --all             # chunks under corpus/parsed/ (gitignored)

# Phase 3 — copy .env.example → .env.local (DATABASE_URL → LAN Postgres), then:
repair-corpus db-migrate
repair-corpus ingest --all                # + local BGE embeddings (free)
repair-corpus search "F5E1 door lock" --model WFW5620HW0

# Phase 5+ — OPENAI_API_KEY in .env.local, app runs on your machine:
repair-corpus ask "What does F5E2 mean?" --model WFW5620HW0
repair-corpus diagnose --model WFW5620HW0

# Web UI — same machine as CLI/API (see docs/DEPLOYMENT.md):
python -m repair_assistant.api.main       # then open http://localhost:8080/ui
```

`repair-corpus` has no `fetch` or `download` subcommand. That is intentional.

**Windows:** if PowerShell says `repair-corpus` is not recognized, the console script
is not on your PATH (common after `pip install -e`). Either add your Python
`Scripts` folder to PATH, or invoke the CLI as a module:

```powershell
python -m repair_assistant.corpus.cli status
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli diagnose --model WFW5620HW0
```

---

## Why applicability is the hard part

A repair instruction can be perfectly correct and still be wrong for your machine. The
corpus is built to make that failure mode visible and testable.

Two real examples from this corpus:

- **Technical Service Pointer W11375982** exists specifically to say that service manual
  W11169652 contains *incorrect information* at "Test #1: ACU Power Check, Step 10". The
  manual is the more detailed, more authoritative-looking document. The bulletin is right
  and the manual is wrong. Relevance and authority are not the same thing.
- **TSP W11395614** is a highly relevant-sounding front-load washer bulletin about a door
  that locks but will not run. It applies to 24-inch models within serial range
  `CF81500000`–`CF84510000`. For a WFW5620HW0 it is simply the wrong document, and
  retrieving it would be a failure no matter how well it matches semantically.

The manifest therefore models model applicability, engineering-digit wildcards, serial
ranges, document revisions, and precedence relationships as first-class data.

---

## Repository layout

```
corpus/manifest/         document manifest (committed)
corpus/documents/        acquired PDFs (gitignored, never committed)
docs/adr/                architecture decision records
docs/corpus/             corpus study and acquisition guide
evals/scenarios/         candidate evaluation scenarios
src/repair_assistant/    application code
tests/                   deterministic tests
```

## Documentation

- [Project charter](docs/CHARTER.md) — vision, constraints, principles, roadmap; ADRs record deviations
- [Corpus licensing and acquisition](docs/CORPUS_LICENSING.md) — copyright, terms of use,
  ServiceMatters confidentiality, why there is no downloader
- [Acquisition guide](docs/corpus/ACQUISITION.md) — how to obtain each document
- [Corpus study](docs/corpus/CORPUS_STUDY.md) — what is actually in these documents
- [Parsing bake-off](evals/parsing/results/scorecard.md) — extractor scores; decision in ADR-0007
- [Infrastructure](docs/INFRASTRUCTURE.md) — LAN Docker + Compose; real host/ports in gitignored local file
- [Deployment](docs/DEPLOYMENT.md) — local app + remote Postgres; optional LAN Docker API
- [Evaluation](docs/EVALS.md) — manual benches at every pipeline layer
- [Langfuse](docs/LANGFUSE.md) — optional self-hosted tracing (ADR-0018)
- [Architecture decision records](docs/adr/) — decisions; must note charter deviations when they occur

## Fixed technology constraints

Python, PostgreSQL, pgvector, Docker, OpenAI, and LangGraph are predetermined in the
[charter](docs/CHARTER.md) (with [documented deviations](docs/CHARTER.md#deviations-from-this-charter)).

**Typical layout:** Postgres on a shared **LAN Docker host**; CLI, API, web UI, and
BGE embeddings on **your machine** — see [Deployment](docs/DEPLOYMENT.md) and
[Infrastructure](docs/INFRASTRUCTURE.md). **LAN-only** (D8); not internet-facing.

Embeddings are local open-source (`BAAI/bge-base-en-v1.5`, ADR-0009 / D1); OpenAI is
reserved for LLM inference. Copy `docs/INFRASTRUCTURE.local.md.example` to
`docs/INFRASTRUCTURE.local.md` for LAN host addresses (gitignored).

## Licence

Application code and project metadata: Apache-2.0. Manufacturer documentation remains the
copyright of its respective owners and is not distributed here.
