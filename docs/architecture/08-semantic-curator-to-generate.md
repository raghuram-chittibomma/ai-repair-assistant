# 08 — Semantic curator through generate

End-to-end path for **opt-in LLM semantic chunking**: a capable model proposes
procedure-scale units on the manufacturer PDF, a human reviews markers on that
PDF, retrieval indexes compact representations, and generate sees a locator stub
plus native PDF layout as primary authority (full `source_text` on the citation
ledger). Structured hybrid parse remains the default for every document until
you promote one.

Drill-downs: curator offline detail in [03 — Offline ingest](03-offline-ingest.md);
retrieval collapse in [04 — Retrieval](04-retrieval.md); ask/diagnose runtime in
[05 — Ask vs diagnose](05-runtime-ask-diagnose.md). Decisions:
[ADR-0047](../adr/0047-ingestion-versions.md) ·
[ADR-0048](../adr/0048-semantic-knowledge-units.md) ·
[ADR-0049](../adr/0049-pdf-native-semantic-boundaries.md) ·
[ADR-0050](../adr/0050-generate-hybrid-pdf-evidence.md) ·
[ADR-0051](../adr/0051-pdf-primary-semantic-evidence.md).

## Why use a strong LLM up front

Repair manuals mix warnings, multi-page procedures, tables, and figures. Fixed
or hybrid-parse chunks optimize for **search recall**; they often split a TEST
procedure from its safety banner or flatten layout the technician sees.

Semantic curation flips the spend: use a **highly capable LLM once at corpus
build** (per high-risk document) to propose page-range units, then keep cheap
local BGE + a smaller generate model at query time. Humans gate cutover on the
real PDF so live retrieval never flips on unreviewed markers.

At answer time the model gets a **locator stub** plus the **native page-range
file part** (or page rasters when scanned) as primary authority; full
`source_text` stays on the citation for UI/claim-binding and as attach-failure
fallback ([ADR-0051](../adr/0051-pdf-primary-semantic-evidence.md)).

## End-to-end (corpus → human → generate)

```mermaid
flowchart TD
  manifest[Manifest_YAML]
  pdf[Manufacturer_PDF]
  structured[Structured_parse_ingest]
  activeStruct[Active_structured_version]
  propose[Propose_semantic_LLM]
  validate[Deterministic_page_validation]
  candidate[Candidate_semantic_version]
  board[Human_review_PDF_js_board]
  finalize[Finalize_reps_ready]
  activate[Activate_cutover]
  activeSem[Active_semantic_version]
  retrieve[Retrieve_overview_facts_questions]
  collapse[Collapse_to_unit_source_text]
  pack[Stub_pack_plus_native_PDF]
  answer[Grounded_ask_or_diagnose]

  manifest --> pdf
  pdf --> structured
  structured --> activeStruct
  activeStruct -->|opt_in_per_doc| propose
  propose --> validate
  validate -->|fail| activeStruct
  validate -->|pass| candidate
  candidate --> board
  board -->|revise_markers| board
  board --> finalize
  finalize --> activate
  activate --> activeSem
  activeSem --> retrieve
  retrieve --> collapse
  collapse --> pack
  pack --> answer
  activeStruct -->|docs_not_promoted| retrieve
```

- **Default path stays free of paid LLM calls:** `parse` / `ingest` only
  ([charter D9](../CHARTER.md#deviations-from-this-charter)).
- **Propose** needs `SEMANTIC_OPENAI_API_KEY`; review, finalize, activate, and
  revert do not.
- **One active version per `doc_id`:** activate supersedes structured in one
  transaction; revert restores structured without re-parse
  ([ADR-0047](../adr/0047-ingestion-versions.md)).
- **Board:** `/ui/corpus` — drag page-fraction handles, split/merge, approve
  units, Finalize (representations), Activate (cutover).

## Build-time detail (propose → ready)

```mermaid
flowchart LR
  pdf[PDF]
  modality{looks_scanned}
  native[Native_PDF_parts]
  rasters[Page_rasters]
  llm[LLM_markers]
  units[Units_thin_extract]
  reps[Overview_facts_questions]
  bge[Local_BGE]
  human[Human_board]
  ready[status_ready]

  pdf --> modality
  modality -->|text| native
  modality -->|scan| rasters
  native --> llm
  rasters --> llm
  llm --> units
  units --> reps
  reps --> bge
  bge --> human
  human --> ready
```

Compact **representations** are what BGE indexes (512-token budget, regenerate
on overflow — never silent truncate). **`source_text`** is a thin PDF extract of
the approved page range — not hybrid-parse enrichment
([ADR-0048](../adr/0048-semantic-knowledge-units.md),
[ADR-0049](../adr/0049-pdf-native-semantic-boundaries.md)).

## Query-time detail (retrieve → generate)

```mermaid
flowchart LR
  q[User_question]
  arms[Retrieval_arms]
  hits[Rep_hits]
  collapse[collapse_semantic_units]
  attach{Text_PDF_or_scan}
  pdfPart[Native_PDF_page_range]
  imgs[Page_rasters]
  stub[Fence_stub_or_text_fallback]
  gen[Generate_LLM]
  cite[Cited_answer]

  q --> arms
  arms --> hits
  hits --> collapse
  collapse --> attach
  attach -->|text_PDF| pdfPart
  attach -->|scanned| imgs
  attach --> stub
  pdfPart --> gen
  imgs --> gen
  stub --> gen
  gen --> cite
```

- Retrieval still uses `active_chunks` and applicability; only the active
  version is searchable.
- Several reps of one unit become **one evidence cite** with the unit’s
  `source_text` on the citation ledger.
- Generate attaches layout first; the fence shows a stub when attach OK
  (full extract on failure). Structured hits send full chunk text (no 2k
  excerpt). Attachments are interleaved by `[n]` rank. Streaming falls back
  to complete when a PDF file part is present. Langfuse records
  `native_pdf_parts` for inspection
  ([ADR-0051](../adr/0051-pdf-primary-semantic-evidence.md),
  [ADR-0050](../adr/0050-generate-hybrid-pdf-evidence.md),
  [LANGFUSE.md](../LANGFUSE.md)).

What the answer LLM sees by hit kind (full table in
[ADR-0051](../adr/0051-pdf-primary-semantic-evidence.md)):

| Hit kind | Fence | Primary authority |
| --- | --- | --- |
| Structured | Full text | Text body |
| Semantic + attach OK | Locator stub | PDF / rasters for `[n]` |
| Semantic + attach failed | Full `source_text` | Text body |

## Surfaces

| Surface | Role |
| --- | --- |
| `repair-corpus segment` / `ingestion-status` / `ingestion-revert` | CLI propose and lifecycle |
| `http://localhost:8080/ui/corpus` | Human review board |
| `POST /v1/ask`, `/v1/diagnose` | Consume active units + PDF attach |
| Langfuse generate `llm` | Text pack + PDF media fingerprint |

**Modules:** `semantic/*`, `retrieval/units.py`, `qa/semantic_evidence.py`,
`api/corpus_routes.py`, `api/static/corpus.html`

## Review board (screenshots)

More context in the README
[Corpus review](../../README.md#corpus-review--semantic-markers) section.

![Corpus review board listing documents by ingestion strategy](../images/ui-corpus-board.png)

![Semantic markers overlaid on the installation instructions PDF](../images/ui-corpus-install-markers.png)

![Selected multi-page marker with Select / Join next controls](../images/ui-corpus-marker-selected.png)
