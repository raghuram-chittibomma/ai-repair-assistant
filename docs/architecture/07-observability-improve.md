# 07 — Observability and improve

Optional Langfuse traces feed a human-reviewed eval mining loop. Tracing is not
required for CLI, UI, or manual benches.

## Improve loop

```mermaid
flowchart LR
  run[Ask_or_diagnose]
  spans[Nested_Langfuse_spans]
  mine[mine_traces]
  draft[Draft_under_evals_qa_drafts]
  human[Human_review]
  promote[promote_eval]
  golden[Golden_fixtures]

  run --> spans
  spans --> mine
  mine --> draft
  draft --> human
  human --> promote
  promote --> golden
```

- **Opt-in:** Empty `LANGFUSE_*` keys → no-op tracing ([ADR-0018](../adr/0018-langfuse-observability.md), [LANGFUSE](../LANGFUSE.md)).
- **Governance:** What traces hold, optional serial redaction, retention, and deletion are documented in [LANGFUSE.md](../LANGFUSE.md#data-governance-review-r44) (review R44).
- **Mine:** `--write` only emits analysis under `evals/qa/drafts/` — no live fixture edits, no auto-promote ([ADR-0023](../adr/0023-trace-driven-eval-mining.md)).
- **Promote:** Human `promote-eval` only; golden fixtures stay under review.
- **Evals:** Layer benches remain the quality bar ([EVALS](../EVALS.md)).

## Nested span tree

When keys are set, each ask / diagnose turn produces nested observations:

```mermaid
flowchart TD
  root[ask_or_diagnose]
  sa[safety_assess]
  ret[retrieval]
  ev[evidence]
  llm[llm_generation]
  sg[safety_gate]

  root --> sa
  root --> ret
  root --> ev
  root --> llm
  root --> sg
```

| Span | Typical payload |
| --- | --- |
| `safety_assess` | Audience, action, reason |
| `retrieval` | Query, hit counts by arm, applicability drops |
| `evidence` | Numbered block sent to the LLM |
| `llm` | Messages in / completion out (generation) |
| `safety_gate` | Post-gate action / rewritten preview |

Traces also stamp `app_git_sha` / `app_started_at` so mined drafts can be tied to a build.

## Mine-traces classification

```mermaid
flowchart TD
  api[Langfuse_API]
  rec[TraceRecord]
  classify[classify_trace]
  codes[Failure_codes]
  stub[Draft_scenario_stub]
  skip[Skip_already_ready]

  api --> rec
  rec --> classify
  classify --> codes
  codes --> stub
  stub --> skip
```

- **Failure codes** (examples): abstain / escalate patterns, procedural answer without citations, clarify-as-abstain — see `eval/mine_traces.py`.
- **Fingerprinting:** Normalized question + failure code avoids duplicate drafts.
- **Ready set:** Questions already covered by golden fixtures are skipped.

**Modules:** `observability/langfuse_tracing.py`, `observability/retrieval_trace.py`, `eval/mine_traces.py`, `eval/promote.py`
