# Docling & GraphRAG evaluation

Evaluation against ADR-0007 (parse) and ADR-0010/0011 (retrieve), plus
**measured** Docling bake-off results (2026-08-26).

**Status:** Docling experiment complete — **parity on fixtures, not adopted as
default**. GraphRAG remains deferred per charter.

---

## Bottom line

| Tool | Decision |
| --- | --- |
| **Docling** | Optional extractor (`--extractor docling`). Matches pdfplumber/pymupdf on all parse fixtures, including hard `error-codes-bound`. **Do not replace pdfplumber as default** — much slower and heavier (local ML models). |
| **GraphRAG** | Still deferred. No demonstrated need beyond manifest relationships + retrieval boosts. |

---

## 1. Docling vs what we considered (parsing)

Historical candidates: **pypdf** (control), **pdfplumber** (ADR-0007 default),
**pymupdf** (alternate). Hard gate: bind F6E1 to its remedy; map PUA bullets;
keep near-dup hashes stable.

| Dimension | Our stack | Docling | After measurement |
| --- | --- | --- | --- |
| Job | Structured chunks for RAG | Layout/table document intelligence | Same layer |
| Tables | pdfplumber/pymupdf table API | TableFormer / layout models | **Passes** `error-codes-bound` |
| Cost / ops | Light; seconds per tech sheet | HF models; ~minutes per large PDF | Keeps it experimental |
| Charter fit | OSS, self-host | OSS MIT (local only; no watsonx) | OK as optional extra |

### How to re-run

```powershell
pip install -e ".[docling]"
# Windows without Developer Mode:
$env:HF_HUB_DISABLE_SYMLINKS = "1"

python -m repair_assistant.corpus.cli bench-parse --write `
  --extractor pypdf --extractor pdfplumber --extractor pymupdf --extractor docling
```

Parse one document:

```powershell
python -m repair_assistant.corpus.cli parse tech-sheet-w11320651 --extractor docling
```

---

## 2. Measured Docling bake-off (2026-08-26)

Source: `evals/parsing/results/scorecard.md` after the command above
(~12 minutes wall clock with Docling; pdfplumber/pymupdf finish in seconds).

| Extractor | Strategy | Hard fixtures | Soft fixtures | Notes |
| --- | --- | --- | --- | --- |
| pypdf | naive_fixed | **FAIL** `error-codes-bound` (F6E1 unbound) | PASS others | Control |
| pdfplumber | structured | **PASS** all | PASS all | ADR-0007 default |
| pymupdf | structured | **PASS** all | PASS all | Alternate |
| docling | structured | **PASS** all | PASS all | Experimental |

Hard fixtures: `error-codes-bound`, `pua-list-markers`. Soft: `near-dup-stable`,
`reflow-not-delta`, `tsp-trilingual`, `mhtml-decode` (mhtml path is shared;
Docling is not used for MHTML).

PUA detail: Docling reported 152 raw markers vs 155 for pdfplumber/pymupdf —
still within the fixture’s unmapped-ratio gate.

### Adoption rule (unchanged)

Do **not** switch default ingestion to Docling unless a future corpus gap
shows pdfplumber failing a hard fixture that Docling uniquely fixes, *and*
operators accept the runtime/model cost. Keep `collapse_overdrawn_connector_labels`
regardless of extractor.

---

## 3. GraphRAG vs what we considered (retrieval / reasoning)

Charter lists GraphRAG / knowledge graphs under “Avoid Premature Complexity.”

| Capability GraphRAG sells | What we already have | Gap? |
| --- | --- | --- |
| Entity/relation graph | Manifest: supersedes, corrected_by, references | Low |
| Multi-hop answers | code_fetch + reference_fetch + connector_fetch | Partial (hand-tuned) |
| Community / global themes | Not needed for ~22-doc family | None for MVP |
| Precedence / conflict | Applicability + authority boosts | Low |
| Dense recall | BGE + `vector_apply_boost` (4/4 hard) | None |

**Keep GraphRAG deferred** until multi-hop failures dominate after exact-id
recall, or the corpus outgrows curated manifest relationships.

---

## 4. Fit to open problems

| Open issue | Docling? | GraphRAG? | Better next step |
| --- | --- | --- | --- |
| J36 / strip-circuit overdraw | **No win** — Docling extract of `W11169652B` had **0** `J36`/`JJ366` hits (label missing, not fixed) | No | Keep overdraw normalizer + connector_fetch on pdfplumber path |
| F3E2 → TEST #10a hop | Indirect | Maybe | Exact/xref fetch + judge |
| Tech sheet A vs multi-model B | No | Overkill | Author `supersedes` in manifest |
| Missing W11355369 | No | No | Acquisition |
| Near-duplicate tech sheets | **PASS** on fixture | No | Preserve fixture before any default swap |

---

## References

- [ADR-0007](adr/0007-parser-and-chunker.md) — parser/chunker selection
- [ADR-0010](adr/0010-retrieval-applicability.md) / [ADR-0011](adr/0011-retrieval-bakeoff.md)
- [CHARTER.md](CHARTER.md) — Avoid Premature Complexity
- Scorecard: `evals/parsing/results/scorecard.md`
- Optional IDE canvas: session artifact `docling-graphrag-eval.canvas.tsx` (this
  file is the durable project copy)
