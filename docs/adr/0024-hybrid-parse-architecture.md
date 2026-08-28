# ADR-0024: Hybrid parse architecture (layout + tables + our chunking)

## Status

Accepted — supersedes the **default extractor** choice in ADR-0007 for
production `parse`; ADR-0007 table-row chunking boundaries and hard fixtures
remain in force.

## Context

Whirlpool service literature mixes layout problems that no single PDF library
solves well:

| Problem | Example | pdfplumber alone |
| --- | --- | --- |
| Grid error-code tables | W11320651 p8 | **Good** — passes `error-codes-bound` |
| Troubleshooting matrices | Guide #1 / #2 | Needs **our** chunker rules (ADR-0022) |
| Two-column procedures | TEST #1 p12 | **Bad** — columns interleaved; steps 9/11 lost |
| PUA bullets / overdraw | Strip-circuit labels | Custom normalizer still required |

Industry practice (and our page-level measurements) show three separable
stages:

1. **Layout understanding** — headings, columns, tables, warnings
2. **Structure reconstruction** — rows, cells, reading order
3. **RAG representation** — deterministic context on chunks (ADR-0022)

Letting one parser own all three creates coupling. Docling passes our table
fixtures but is slow (~minutes/doc) and did not fix J36 overdraw. PyMuPDF4LLM
fixes page-12 reading order at low cost but is weaker as the sole table engine.

## Decision

### 1. Default extractor: `hybrid`

Production `repair-corpus parse` uses a **page-scoped router**, not a single
library:

```
PDF page
   │
   ├─ classify layout (matrix | multi_column | table_heavy | default)
   │
   ├─ tables  → pdfplumber extract_tables()  (always)
   │
   ├─ prose   → matrix: pdfplumber LTR (never column-reorder)
   │         → multi_column: left-then-right / pymupdf4llm
   │         → else: pdfplumber text
   │
   ├─ parse_quality audit (reading order, table column variance, …)
   │
   └─ suspect multi_column ? retry layout path once → ExtractedDocument
```

**Table extraction stays on pdfplumber** inside hybrid — it owns the
`error-codes-bound` hard gate.

**Matrix vs multi_column:** Vertical rules on troubleshooting guides are
*table* column separators. Applying newspaper left-then-right reading order
severs Problem/Cause from Checks. Those pages are classified ``matrix`` and
keep LTR ``extract_text``, then the generic matrix prose fallback
(``table_context.parse_troubleshooting_prose``) rebuilds Guide #1/#2 rows.

**Prose / reading order** for procedure pages (TEST #1) still uses column
reorder / layout ML when classified ``multi_column``.

### 2. Canonical document tree (parser output)

Extractors emit `ExtractedDocument` (backward compatible) plus an optional
`CanonicalDocument` tree:

```
CanonicalDocument
 ├── page nodes
 │    ├── heading
 │    ├── paragraph / procedure
 │    └── table (headers + rows)
 └── parse_audit (per-page layout, parser used, quality flags)
```

The **chunker consumes `ExtractedDocument`** today; canonical tree is persisted
in `parse_audit.json` for debugging and future policy hooks. Parser tells us
*what* the document contains; **our chunker** decides RAG representation
(error row, matrix row, procedure step, ADR-0022 context).

### 3. Parse quality audit (before chunking)

Deterministic per-page signals (`parse_quality.py`):

| Signal | Trigger |
| --- | --- |
| `reading_order_suspect` | Phrase markers out of order; missing numbered steps; or multi_column still on raw pdfplumber |
| `table_column_variance` | Row cell counts vary widely vs header width |
| `matrix_no_data_rows` | Troubleshooting matrix detected but zero data rows |

**Generic vs document-specific:** layout classification and most audit signals are
Whirlpool-family / content-based (matrix headers, TEST # procedures, column
geometry, contiguous `N.` step spans). When a *particular* sheet needs stronger
checks (known phrase order on a hard procedure page), add an entry to
[`config/parsing/quality_overrides.yaml`](../../config/parsing/quality_overrides.yaml)
matched by publication / filename / page — **never** hardcode absolute page
numbers or publication ids in Python. Override path can be redirected with
`REPAIR_PARSE_QUALITY_CONFIG`.

Suspect pages retry the layout prose path once. Table fallback to Docling /
PaddleOCR / Unstructured is **deferred** — hooks are documented, not implemented.

### 4. Extractor registry

| Name | Role |
| --- | --- |
| `hybrid` | **Production default** |
| `pdfplumber` | Table baseline; bake-off control |
| `pymupdf` | Layout blocks alternate |
| `pymupdf4llm` | Layout prose path (optional `[layout]` extra) |
| `docling` | Experimental full-doc ML (`[docling]` extra) |
| `pypdf` | Naive control |

### 5. Chunking unchanged in ownership

ADR-0007 split boundaries + ADR-0022 enrichment + troubleshooting matrix
rules (`table_context.py`) remain **our** layer. No parser-owned hierarchical
chunker (Docling hybrid chunker is reference only).

### 6. Evaluation extension

Add `procedure-reading-order` fixture (W11320651 p12): monotonic phrase markers
and steps 1–13 present — expectations live in the eval fixture **and** optionally
in `config/parsing/quality_overrides.yaml` for hybrid audit retries. Hard gates
unchanged: `error-codes-bound`, `pua-list-markers`. Future: 20-page difficult-page
set + `bench-chain` retrieval check (EVAL_FRAMEWORK_GAPS E12 triggers).

## Consequences

- `corpus/parsed/<doc_id>/parse_audit.json` records per-page routing decisions.
- Re-parse changes chunk hashes → re-embed (ADR-0008).
- Optional install: `pip install -e ".[layout]"` for pymupdf4llm layout path;
  hybrid degrades to pdfplumber column reorder without it.
- ADR-0007 remains the table/chunking ADR; this ADR owns **extractor routing**
  and **canonical intermediate representation**.
- Commercial parsers (LlamaParse, Google Document AI, Azure) stay **benchmark
  references only** — not production dependencies.

## Deferred (explicit hooks, not in scope)

- PaddleOCR PP-StructureV3 table-only fallback on `table_structure_suspect`
- Unstructured `hi_res` challenger bake-off on ~20 difficult pages
- Semantic troubleshooting normalization (structured fields + original text)
- Docling as automatic table fallback (cost/runtime)

## References

- [ADR-0007](0007-parser-and-chunker.md) — table-row chunking; pdfplumber table engine
- [ADR-0022](0022-contextual-chunk-enrichment.md) — contextual chunk text
- [DOCLING_GRAPHRAG_EVAL.md](../corpus/DOCLING_GRAPHRAG_EVAL.md) — Docling measured parity
- Implementation: `parsing/hybrid.py`, `column_order.py`, `parse_quality.py`, `canonical.py`
