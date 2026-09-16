# ADR-0048: Semantic knowledge units and retrieval representations

## Status

**Partially superseded** by [ADR-0049](0049-pdf-native-semantic-boundaries.md)
(boundary expression and `source_text` assembly). Unit-vs-representation split,
over-limit rejection, curator opt-in, and representation kinds remain in force.
Builds on [ADR-0047](0047-ingestion-versions.md). **Narrows
[ADR-0009](0009-local-open-embeddings.md) decision 3**: `repair-corpus ingest`
stays free of paid API calls, and the carve-out is limited to an explicitly
operator-invoked curator step. Does not change the default chunker
([ADR-0007](0007-parser-and-chunker.md), [ADR-0022](0022-contextual-chunk-enrichment.md))
or the embedder ([ADR-0009](0009-local-open-embeddings.md) decisions 1, 2, 4, 5).

## Context

`BAAI/bge-base-en-v1.5` truncates at 512 tokens. Structured chunking respects
that by cutting on document structure, which works for tech-sheet table rows but
splits a multi-page diagnostic procedure away from the warning that governs it.
The hypothesis worth testing is that a few high-value manuals do better when an
LLM decides what must stay together, and a human checks that decision.

The obstacle is that ADR-0009 decision 3 says no paid calls during ingest, for a
good reason: ingest must stay reproducible and free, and `OPENAI_API_KEY` must
not become a precondition for standing up the corpus.

That constraint survives if segmentation is not part of ingest. Parsing and
ingest remain deterministic and key-free; segmenting a chosen document is a
separate curator action, like `pin` or `promote-eval`.

## Options

Where the retrieval vector and the generation content come from:

| | A — Embed the whole unit | B — Unit is content, compact representations are searchable | C — Summarise for generation too |
| --- | --- | --- | --- |
| Units may exceed 512 tokens | No — BGE truncates silently | Yes | Yes |
| Generation sees original source | Yes | Yes | **No** |
| Recall surfaces per unit | 1 | Several | Several |
| Choice | Rejected — the truncation this ADR exists to avoid | **Accepted** | Rejected — ungrounded answers |

How the model expresses a boundary:

| | D — Model emits the unit text | E — Model selects parsed anchor ids |
| --- | --- | --- |
| Can hallucinate source content | Yes | **Structurally impossible** |
| Can hallucinate page numbers | Yes | No — pages derived from anchors |
| Validation available | Fuzzy match | Exact set membership |
| Choice | Rejected | **Accepted** |

## Decision

1. **Two artefacts, one authority.** A `semantic_units` row holds `source_text`,
   assembled by concatenating the parsed chunk bodies its span covers. Retrieval
   representations are separate `chunks` rows carrying `unit_id` and `rep_kind`.
   The unit is what reaches the answer-generation LLM; representations exist only
   for discovery.
2. **The model selects anchors, never prose.** A proposal is a list of
   `{start_anchor, end_anchor, title, unit_type}` over parsed `chunk_id`s given
   to it in reading order. Hallucinated content and hallucinated page references
   are therefore unrepresentable rather than merely detected: page ranges are
   derived from the anchors the model picked.
3. **Deterministic validation is the gate.** Anchors must exist, be ordered,
   not overlap, leave no gap, and produce non-empty units; no `table_row` or
   `heading` anchor may be dropped. A failed proposal leaves the version
   `candidate` and the legacy version serving traffic.
4. **Three representation kinds to start** — `overview`, `facts`, `questions` —
   behind a registry so a fourth is additive.
5. **Over-limit representations are rejected, not truncated.** A representation
   above the BGE budget is regenerated under a tighter instruction and surfaced
   to the reviewer if it still does not fit. Silent truncation is the failure
   mode this ADR exists to prevent, so it is never the fallback.
6. **The curator step is opt-in and separate.** `repair-corpus segment <doc_id>`
   and the review UI are the only entry points that read `OPENAI_API_KEY`.
   `parse` and `ingest` are unchanged and still run without one.
7. **Model choice stays configuration.** Segmentation goes through the existing
   `OpenAIClient` with a strict `json_schema` response format and `LLM_MODEL` /
   `SEMANTIC_LLM_MODEL`. No module hardcodes a snapshot.
8. **The proposal is kept.** `semantic_proposals` stores the exact context sent,
   the raw output, and the validation result; `semantic_units.origin` and
   `.edits` record what a human changed. That is the training-data substrate, not
   a fine-tuning implementation.

**Charter deviation:** [D9](../CHARTER.md#deviations-from-this-charter) — a paid
LLM call now exists on the ingestion side of the system, bounded to the curator
step.

## Consequences

- Segmenting a document costs OpenAI tokens proportional to its parsed size.
  Bounded by being opt-in per document and cached in `semantic_proposals`.
- A promoted document stores `source_text` again alongside its parsed chunks.
  Acceptable duplication for a 22-document corpus; it is what lets generation
  read the unit without re-reading the JSONL at query time.
- Representations are generated content, so they must never be cited as source.
  Citations resolve to the parent unit's page range.
- Measured by parsing and unit fixtures plus a `bench-retrieve` parity run on the
  untouched documents. A semantic-vs-structured retrieval comparison needs an
  evaluation mode that is deliberately not built here.

## See also

[architecture/08 — Semantic curator → generate](../architecture/08-semantic-curator-to-generate.md) · [ADR-0049](0049-pdf-native-semantic-boundaries.md) · [ADR-0050](0050-generate-hybrid-pdf-evidence.md)
