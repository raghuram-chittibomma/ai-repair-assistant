# 03 — Offline ingest

Build-time path from manufacturer files to searchable chunks. No downloader in
the repo — you acquire PDFs yourself, then `parse` → `ingest`.

This page has four views: **end-to-end**, **hybrid parse** (page-scoped router),
**chunking + bounded quality repair**, and the opt-in **semantic curator** path.

## End-to-end

```mermaid
flowchart LR
  manifest[Manifest_YAML]
  acquire[Acquire_PDFs]
  parse[Hybrid_parse]
  chunk[Chunk_enrich_quality]
  embed[Local_BGE_embed]
  store[(Postgres_upsert)]

  manifest --> acquire
  acquire --> parse
  parse --> chunk
  chunk --> embed
  embed --> store
```

- **Manifest first:** Identity, applicability, precedence, hashes ([ADR-0001](../adr/0001-corpus-manifest-format.md), [ADR-0004](../adr/0004-applicability-and-precedence.md)).
- **No fetch:** Verify-only tooling; PDFs never enter git ([ADR-0003](../adr/0003-no-downloader.md)).
- **Parse ≠ chunk:** Layout routing and table extraction are separate from RAG chunk boundaries ([ADR-0024](../adr/0024-hybrid-parse-architecture.md), [ADR-0007](../adr/0007-parser-and-chunker.md)).
- **Ingest:** Fingerprint skip for unchanged docs; local `BAAI/bge-base-en-v1.5` ([ADR-0008](../adr/0008-incremental-ingestion.md), [ADR-0009](../adr/0009-local-open-embeddings.md)).
- **Versioned output:** Every chunk belongs to an `ingestion_versions` row. `ingest` writes the document's `structured` version and refuses to overwrite a document whose active version is `semantic_llm` ([ADR-0047](../adr/0047-ingestion-versions.md)).

## Hybrid parse (per page)

Production `repair-corpus parse` uses the **hybrid** extractor — a page-scoped
router, not one PDF library for everything. Tables stay on pdfplumber; prose
reading order depends on layout class.

```mermaid
flowchart TD
  pdf[PDF_page]
  tables[pdfplumber_tables]
  dropJunk[drop_junk_tables]
  classify[page_classify]
  proseRouter{Layout_class}
  matrixLTR[Matrix_LTR]
  ltrProse[TOC_schematic_figure_LTR]
  multiCol[Multi_column_reorder]
  defaultProse[Default_prose]
  matrixFallback[parse_troubleshooting_prose]
  audit[parse_quality_audit]
  overrides[quality_overrides_yaml]
  canon[CanonicalDocument_tree]
  extracted[ExtractedDocument]

  pdf --> tables
  tables --> dropJunk
  dropJunk --> classify
  classify --> proseRouter
  proseRouter -->|matrix| matrixLTR
  proseRouter -->|toc schematic figure| ltrProse
  proseRouter -->|multi_column photo_access| multiCol
  proseRouter -->|default table_heavy| defaultProse
  matrixLTR --> matrixFallback
  dropJunk --> audit
  ltrProse --> audit
  multiCol --> audit
  defaultProse --> audit
  matrixFallback --> audit
  overrides -.-> audit
  audit --> canon
  audit --> extracted
  canon --> extracted
```

- **Classify:** `matrix` | `toc` | `schematic` | `figure` | `photo_access` | `table_heavy` | `multi_column` | `default` — wrong class breaks error tables or TEST # procedures ([ADR-0024](../adr/0024-hybrid-parse-architecture.md)). The layout-pack checklist is `evals/parsing/layout-pack.yaml` (`repair-corpus bench-layout`).
- **Tables:** `pdfplumber` `extract_tables()`, then drop artwork / warning-box grids — owns the `error-codes-bound` hard gate.
- **LTR pages:** `matrix`, `toc`, `schematic`, `figure` keep pdfplumber left-to-right text. Matrix vertical rules are table columns, not newspaper columns. Guide #1 / #2 rows rebuilt via `table_context.parse_troubleshooting_prose` when grids are missed.
- **Multi-column / photo-access:** Left-then-right / layout path for TEST # procedures and component-access pages with photos.
- **Audit:** Per-page reading-order and table-variance signals; config overrides in `config/parsing/quality_overrides.yaml`.
- **Output:** Backward-compatible `ExtractedDocument` plus optional `CanonicalDocument` tree with `parse_audit` JSON.

**Modules:** `parsing/hybrid.py`, `parsing/page_classify.py`, `parsing/parse_quality.py`, `parsing/canonical.py`, `parsing/table_context.py`

## Chunking and bounded quality repair

Chunk boundaries follow ADR-0007 (table-row / heading-aware prose). **Contextual
enrichment** adds doc title, section path, and headers into embed text. A
**single-pass** audit→repair→re-audit loop improves opaque rows without
re-parsing the PDF.

```mermaid
flowchart TD
  doc[ExtractedDocument]
  banner[Reset_section_from_running_header]
  filter[Drop_junk_tables_skip_figure_prose]
  split{Chunk_strategy}
  errorRow[Error_code_table_row]
  matrixRow[Troubleshooting_matrix_row]
  proseChunk[Heading_aware_prose]
  enrich[format_contextual_text]
  audit1[Quality_audit]
  repair{Repairable_finding}
  applyRepair[Safe_metadata_repair]
  audit2[Re_audit]
  out[chunks_jsonl]
  report[chunk_quality_json]

  doc --> banner
  banner --> filter
  filter --> split
  split --> errorRow
  split --> matrixRow
  split --> proseChunk
  errorRow --> enrich
  matrixRow --> enrich
  proseChunk --> enrich
  enrich --> audit1
  audit1 --> repair
  repair -->|yes_one_pass| applyRepair
  repair -->|no_or_flag_only| audit2
  applyRepair --> audit2
  audit2 --> out
  audit2 --> report
```

- **Structured splits:** One row per error-code / matrix data row; prose by heading — not fixed-size splits ([ADR-0007](../adr/0007-parser-and-chunker.md)).
- **Headings:** TOC dotted `TEST #` rows and note sentences are not section banners; each page resets `section_path` from the running header when present ([ADR-0022](../adr/0022-contextual-chunk-enrichment.md)).
- **Skip / drop:** Schematic and figure prose stay out of the index (keep real pin tables). Artwork and shock-box “tables” are dropped.
- **Matrix chunks:** Guide #1 (`problem_spanned`) and Guide #2 (`group_symptom`) inherit problem anchors and group notes in metadata + embed text ([ADR-0022](../adr/0022-contextual-chunk-enrichment.md)). Guide #1 anchors are OEM problem names in title case or ALL CAPS (`Door Won't Unlock`, `WON'T POWER UP`); cause sentences with a period are not anchors ([ADR-0042](../adr/0042-guide1-anchor-and-checklist-coalesce.md)).
- **Enrich:** `doc_title`, `section_path`, `Header: value` keyed rows so retrieval sees context, not bare numbers.
- **Self-improve:** `audit_and_improve` — at most **one** repair pass (`MAX_REPAIR_PASSES = 1`); flag-only findings (e.g. unbound error codes) never auto-merge; persists `chunk_quality.json` beside `chunks.jsonl`.
- **Offline only:** LLM header suggestions and re-parse never chain from live ask/diagnose.

**Modules:** `parsing/chunker.py`, `parsing/chunk_quality.py`, `parsing/write.py`

## Semantic curator (opt-in, per document)

Structured chunking above stays the default for every document. A document may
instead be **promoted** to `semantic_llm`, where an LLM proposes PDF page-range
markers (native PDF, or vision rasters when scanned), a human checks them on
the real PDF, and the new representation replaces the old one in a single
transaction
([ADR-0047](../adr/0047-ingestion-versions.md), [ADR-0049](../adr/0049-pdf-native-semantic-boundaries.md)).

```mermaid
flowchart TD
  pdf[Manufacturer_PDF]
  route{looks_scanned}
  native[Native_PDF_parts]
  vision[Page_rasters]
  candidate[ingestion_version_candidate]
  llm[LLM_page_range_markers]
  validate[Deterministic_page_validation]
  units[semantic_units_thin_PDF_extract]
  reps[Overview_facts_questions]
  budget{Within_512_tokens}
  embed[Local_BGE_embed_rep_rows]
  review[PDF_js_review_board]
  ready[status_ready]
  cutover[Activate_supersede_structured]
  legacy[Structured_version_keeps_serving]

  pdf --> route
  route -->|no| native
  route -->|yes| vision
  native --> candidate
  vision --> candidate
  candidate --> llm
  llm --> validate
  validate -->|fail| legacy
  validate -->|pass| units
  units --> reps
  reps --> budget
  budget -->|no| reps
  budget -->|yes| embed
  embed --> review
  review --> ready
  ready --> cutover
```

- **PDF page markers, not parsed anchors:** The model returns `{start_page, end_page, start_y, end_y, title, unit_type}` over the PDF part it was given ([ADR-0049](../adr/0049-pdf-native-semantic-boundaries.md)).
- **Validation is the gate:** pages in bounds, ordered, no overlap, full window coverage. A failure leaves the candidate in place and the structured version serving traffic.
- **Unit vs representation:** `semantic_units.source_text` is a thin PDF extract of the page range (not hybrid-parse enrichment) and is what reaches the answer LLM. The searchable `chunks` rows are compact `overview` / `facts` / `questions` surfaces carrying `unit_id` + `rep_kind`. An over-budget representation is regenerated, then surfaced to the reviewer — never truncated. Empty extracts on scanned units block activate until OCR exists.
- **Cutover:** `approve` marks the version `ready`; `activate` flips it to `active` and supersedes the structured version in one transaction. `revert` activates the structured version again without re-parsing.
- **Key-free ingest:** `parse` and `ingest` never call OpenAI. Only `repair-corpus segment` and the review board do (charter [D9](../CHARTER.md#deviations-from-this-charter)).

**Modules:** `semantic/segment.py`, `semantic/pdf_extract.py`, `semantic/validate.py`, `semantic/units.py`, `semantic/representations.py`, `semantic/tokens.py`, `semantic/review.py`, `semantic/curate.py`, `semantic/lifecycle.py`, `semantic/store.py`

---

**CLI:** `repair-corpus parse` · `repair-corpus ingest` · `repair-corpus segment` · `repair-corpus ingestion-status` · `repair-corpus ingestion-revert` · `repair-corpus bench-layout` · [Reference corpus build](../REFERENCE_CORPUS_BUILD.md)
