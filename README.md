# AI Repair Assistant

Appliance repair needs **authoritative manufacturer knowledge**, not generic LLM advice.
This is a self-hostable framework for **grounded ask** and **multi-turn diagnose** over your
own service manuals and tech sheets — with numbered citations, model/serial applicability
filters, and deterministic safety gates before answers reach the user.

It was proven end-to-end on a **Whirlpool front-load washer reference corpus**
(WFW5620H / WFW5620HW0). The application code is reusable; PDFs stay out of git and
you supply the brand-specific manifest and documents. See
[Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md) to reproduce that setup.

> **Phase 11 complete.** LAN-only deployment ([charter](docs/CHARTER.md), constraint D8).
> Web UI at `http://localhost:8080/ui` after [Deployment](docs/DEPLOYMENT.md).
> Optional [Langfuse](docs/LANGFUSE.md) traces; `mine-traces` drafts evals from live failures
> ([ADR-0023](docs/adr/0023-trace-driven-eval-mining.md)).

---

## How we built it

Each pipeline layer went through the same loop: **charter phase → measure → ADR → implement → bench** — not “ship prompts and hope.”

| Experiment | Outcome |
| --- | --- |
| Parser bake-off | pdfplumber + structured table rows ([ADR-0007](docs/adr/0007-parser-and-chunker.md)); later hybrid layout routing ([ADR-0024](docs/adr/0024-hybrid-parse-architecture.md)) |
| Retrieval arms | Hybrid re-test kept the product gate at 14/14 hard ([ADR-0010](docs/adr/0010-retrieval-applicability.md), [ADR-0020](docs/adr/0020-hybrid-retrieval-retest.md)) |
| Safety | Deterministic allow / warn / escalate / block — not LLM-only ([ADR-0014](docs/adr/0014-safety-policy.md)) |
| Traces → evals | Langfuse spans mined into human-reviewed draft scenarios ([ADR-0018](docs/adr/0018-langfuse-observability.md), [ADR-0023](docs/adr/0023-trace-driven-eval-mining.md)) |
| Semantic curator | Opt-in LLM page-range units for high-risk PDFs; human board before cutover; generate is PDF-primary for semantic cites ([ADR-0047](docs/adr/0047-ingestion-versions.md)–[ADR-0051](docs/adr/0051-pdf-primary-semantic-evidence.md)) |

Full decision log: [Architecture decision records](docs/adr/README.md).
Manual benches at every layer: [Evaluation](docs/EVALS.md).

---

## Capabilities by pipeline layer

```mermaid
flowchart LR
  docs[Manufacturer_PDFs] --> parse[Hybrid_parse]
  parse --> chunk[Structured_chunking]
  chunk --> ingest[Embed_and_store]
  ingest --> retrieve[Hybrid_retrieval]
  retrieve --> ground[Grounded_ask]
  retrieve --> diagnose[Multi_turn_diagnose]
  ground --> safety[Safety_gates]
  diagnose --> safety
  safety --> ui[LAN_UI_API]
  ui --> traces[Langfuse_traces]
  traces --> mine[mine_traces_improve]
  docs -.->|opt_in_high_risk| curator[Semantic_curator]
  curator --> human[Human_PDF_board]
  human --> ingest
```

- **Parsing** — hybrid page router (matrix / TOC / schematic / photo-access / multi-column), quality overrides ([ADR-0024](docs/adr/0024-hybrid-parse-architecture.md))
- **Chunking (default)** — table-row / matrix / contextual enrichment; Guide #1 title-case or ALL-CAPS anchors ([ADR-0007](docs/adr/0007-parser-and-chunker.md), [ADR-0022](docs/adr/0022-contextual-chunk-enrichment.md), [ADR-0042](docs/adr/0042-guide1-anchor-and-checklist-coalesce.md))
- **Semantic chunking (opt-in)** — spend a **highly capable LLM once at corpus build** on high-risk manuals (install / repair procedures) so units keep warnings with their TEST steps; a human reviews markers on the real PDF before activate; retrieval indexes compact reps; **generate treats native PDF/rasters as primary** (stub in the text fence; `source_text` is audit/fallback only) ([ADR-0047](docs/adr/0047-ingestion-versions.md)–[ADR-0051](docs/adr/0051-pdf-primary-semantic-evidence.md), [architecture/08](docs/architecture/08-semantic-curator-to-generate.md))
- **Retrieval** — vector + codes/connectors, applicability, owner-preferring literature when feasible; door polarity is grammar, not slang YAML; same-problem rows coalesce into one citation; semantic hits collapse to a unit cite ([ADR-0010](docs/adr/0010-retrieval-applicability.md), [ADR-0040](docs/adr/0040-door-polarity-grammar.md), [ADR-0041](docs/adr/0041-unlock-family-no-fault-code.md), [ADR-0042](docs/adr/0042-guide1-anchor-and-checklist-coalesce.md))
- **Grounded Q&A / diagnose** — citations, abstain, checklist path discipline, gated source-page overlay and row/prose highlight, diagnose session tally ([ADR-0012](docs/adr/0012-grounded-qa.md), [ADR-0013](docs/adr/0013-langgraph-diagnostic.md), [ADR-0036](docs/adr/0036-ui-source-page-images.md)–[ADR-0038](docs/adr/0038-paragraph-highlight.md), [ADR-0044](docs/adr/0044-diagnose-session-tally.md)–[ADR-0046](docs/adr/0046-current-span-protocol.md))
- **Safety** — block / escalate / post-LLM gates; owner vs technician ([ADR-0014](docs/adr/0014-safety-policy.md))
- **Improve from traces** — Langfuse → `mine-traces` reports → human promote ([ADR-0018](docs/adr/0018-langfuse-observability.md), [ADR-0023](docs/adr/0023-trace-driven-eval-mining.md))

### Shared retrieve → generate fork

Structured and `semantic_llm` docs share the same query plan, fetch arms, and
ranking. What differs is the row type in `active_chunks` and the generate
payload: full chunk text (plus optional gated figure-page JPEGs) vs locator
stub + native PDF page-range
([ADR-0051](docs/adr/0051-pdf-primary-semantic-evidence.md),
[ADR-0035](docs/adr/0035-multimodal-figure-evidence.md)). Drill-down:
[architecture/04](docs/architecture/04-retrieval.md).

```mermaid
flowchart TD
  q[Query]
  plan[plan_for_query]
  db[(active_chunks)]
  vec[vector_fetch]
  code[code_fetch]
  conn[connector_fetch]
  ref[reference_fetch]
  rev[manual_rev_fetch]
  merge[merge_hits]
  apply[document_applies]
  boost[Light_boosts_plus_owner_pref]
  ranked[Final_ranked_list]
  fork{Hit_strategy}
  structHit[Structured_chunk_text]
  semReps[Semantic_rep_hits]
  collapse[collapse_semantic_units]
  unitCite[One_unit_cite_source_text_on_ledger]
  packS[format_evidence_full_text]
  gated[attach_gated_images_optional]
  packU[format_evidence_stub]
  packF[format_evidence_source_text_fallback]
  attach[attach_semantic_pdf_or_rasters]
  gen[Answer_LLM]

  q --> plan
  plan --> vec
  plan --> code
  plan --> conn
  plan --> ref
  plan --> rev
  db -.->|structured_rows_or_reps| vec
  db -.-> code
  db -.-> conn
  db -.-> ref
  db -.-> rev
  vec --> merge
  code --> merge
  conn --> merge
  ref --> merge
  rev --> merge
  merge --> apply
  apply --> boost
  boost --> ranked
  ranked --> fork
  fork -->|structured| structHit
  fork -->|semantic_llm| semReps
  structHit --> packS
  structHit -->|figure_schematic_cite| gated
  packS --> gen
  gated -->|page_JPEG_rasters| gen
  semReps --> collapse
  collapse --> unitCite
  unitCite --> attach
  attach -->|ok| packU
  attach -->|fail| packF
  packU --> gen
  packF --> gen
  attach -->|PDF_primary_body| gen
```

| Stage | Structured | `semantic_llm` |
| --- | --- | --- |
| Arms match | Enriched chunk text | Compact reps (search surface only) |
| Ranking | Shared applicability → boosts → owner pref | Same |
| Generate | Full text in fence; **optional** gated page JPEGs for figure/schematic cites | Stub + native PDF/rasters (primary); `source_text` is audit/fallback |

**Architecture (drill-down):** [System context](docs/architecture/01-system-context.md) · [Deployment](docs/architecture/02-deployment.md) · [Offline ingest](docs/architecture/03-offline-ingest.md) · [Retrieval](docs/architecture/04-retrieval.md) · [Ask vs diagnose](docs/architecture/05-runtime-ask-diagnose.md) · [Safety](docs/architecture/06-safety.md) · [Observability](docs/architecture/07-observability-improve.md) · [Semantic curator → generate](docs/architecture/08-semantic-curator-to-generate.md) — index: [docs/architecture/](docs/architecture/)

---

## Product screenshots

### Ask — cited answer

Grounded one-shot Q&A with numbered citation chips tied to manifest documents.

![Ask mode with citation chips](docs/images/ui-ask-cited.png)

### Diagnose — owner checklist (turn 1)

Session path tally (symptom, offered checks, citation chip), coalesced checklist, and the gated source page with a row highlight.

![Owner diagnostic chat with session tally and source-page highlight](docs/images/ui-diagnose-checklist.png)

### Diagnose — progress follow-up (turn 2)

After “checked / no issues,” the tally moves those steps to **Checked** and keeps the same `[n]` while the chat continues the path.

![Diagnose follow-up with cleared checks on the session path](docs/images/ui-diagnose-tech-multiturn.png)

### Diagnose — symptom change

A corrected problem appends a **Symptom changed** span. Checks from the first complaint stay there; **Now asking** is the new path.

![Session path tally after the door opens but will not close](docs/images/ui-diagnose-symptom-change.png)

### Diagnose — source-page highlight

Click `[n]` or expand Source page to overlay the cited table row or prose span on the same JPEG the model saw.

![Source page with cited-row highlight and session path](docs/images/ui-diagnose-highlight.png)

### Safety — escalate before unsafe guidance

Pre-LLM escalation banner and post-generation gate when owner audience requests live-voltage work.

![Safety escalation banner for owner voltage question](docs/images/ui-safety-escalate.png)

### Langfuse — trace detail

Retrieve, evidence, LLM, and safety_gate spans for the same ask/diagnose runs ([LANGFUSE.md](docs/LANGFUSE.md)).

![Langfuse trace with retrieve, evidence, llm, and safety_gate spans](docs/images/langfuse-trace.png)

### Corpus review — semantic markers

Opt-in curator at `http://localhost:8080/ui/corpus`. Structured docs stay on the
default parse path; promote a high-risk PDF when procedure-scale units matter.
Full flow: [architecture/08](docs/architecture/08-semantic-curator-to-generate.md).

**Board overview** — per-document strategy (`structured` vs `semantic_llm`) and review status.

![Corpus review board listing documents by ingestion strategy](docs/images/ui-corpus-board.png)

**Markers on the manufacturer PDF** — LLM-proposed page ranges overlaid for human check; live approved list on the right.

![Corpus review with semantic markers on installation instructions PDF](docs/images/ui-corpus-install-markers.png)

**Select / split / join** — drag page-fraction handles, join neighbors, then Finalize representations and Activate cutover (retrieval stays on the prior active version until activate).

![Corpus review with a multi-page installation-parts marker selected](docs/images/ui-corpus-marker-selected.png)

---

## Get started

Assumes Postgres is up, `.env.local` is configured, and a corpus is ingested.
Full install: [Deployment](docs/DEPLOYMENT.md).

```bash
uv sync --frozen --extra dev

# API + UI (same machine)
uv run python -m repair_assistant.api.main
# open http://localhost:8080/ui
# corpus curator: http://localhost:8080/ui/corpus
```

`uv.lock` pins the resolved environment so ADR scorecards can be regenerated.
`pip install -e ".[dev]"` still works but is not the reproducible path.

CLI (Windows-friendly module form):

```powershell
python -m repair_assistant.corpus.cli search "door won't lock" --model WFW5620HW0
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli diagnose --model WFW5620HW0
```

**No corpus yet?** [Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md) (acquire → parse → ingest), then return here.

**As a framework:** describe documents in `corpus/manifest/`, acquire PDFs under `corpus/documents/` (gitignored), `parse` → `ingest` → ask / diagnose / UI. For high-risk manuals, optionally `segment` → review on `/ui/corpus` → activate ([ADR-0047](docs/adr/0047-ingestion-versions.md)–[ADR-0049](docs/adr/0049-pdf-native-semantic-boundaries.md)). Keep eval fixtures and ADRs as the quality bar when you change chunking or retrieval.

---

## Documents are not in this repository

Manufacturer manuals and tech sheets are copyrighted and **never** committed here.
The repo ships a **manifest** (what should exist, hashes, applicability) and tools to
verify what you acquired — the same idea as Nixpkgs `requireFile` or MAME software lists.
There is no `fetch` / `download` command. Details: [Corpus licensing](docs/CORPUS_LICENSING.md).

---

## Repository layout

```
corpus/manifest/         document manifest (committed)
corpus/documents/        acquired PDFs (gitignored, never committed)
docs/adr/                architecture decision records
docs/architecture/       multi-level Mermaid diagrams
docs/images/             README screenshots
evals/                   evaluation fixtures and scorecards
src/repair_assistant/    application code
tests/                   deterministic tests
```

## Documentation

- [Deployment](docs/DEPLOYMENT.md) — API/UI/CLI against LAN Postgres; `/ui` chat and `/ui/corpus` curator
- [Architecture diagrams](docs/architecture/) — system, deploy, ingest, retrieve, runtime, safety, traces, [semantic curator → generate](docs/architecture/08-semantic-curator-to-generate.md)
- [Evaluation](docs/EVALS.md) — manual benches at every pipeline layer
- [Architecture review](docs/ARCHITECTURE_REVIEW.md) — external audit, 48 findings
- [Review response](docs/ARCHITECTURE_REVIEW_RESPONSE.md) — claims re-verified, disposition per finding, remediation slices
- [Project charter](docs/CHARTER.md) — vision, constraints, roadmap
- [Langfuse](docs/LANGFUSE.md) — optional self-hosted tracing
- [Architecture decision records](docs/adr/) — design decisions ([0047](docs/adr/0047-ingestion-versions.md)–[0050](docs/adr/0050-generate-hybrid-pdf-evidence.md) for semantic units)
- [Reference corpus build](docs/REFERENCE_CORPUS_BUILD.md) — Whirlpool acquire → ingest (optional semantic promote)
- [Corpus licensing](docs/CORPUS_LICENSING.md) — copyright; no downloader

## Stack

Python, PostgreSQL, pgvector, Docker, OpenAI, LangGraph ([charter](docs/CHARTER.md)).
Postgres on a **LAN Docker host**; CLI, API, UI, and local BGE embeddings on **your machine**
([ADR-0009](docs/adr/0009-local-open-embeddings.md)). OpenAI is for LLM inference only.

## Licence

Application code and project metadata: Apache-2.0. Manufacturer documentation remains the
copyright of its respective owners and is not distributed here.
