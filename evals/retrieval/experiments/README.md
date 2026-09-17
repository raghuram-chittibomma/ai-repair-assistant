# Retrieval experiments (not S4)

Draft bake-offs and investigations that are **not** the decision set in
`evals/retrieval/fixtures.yaml`. Do not treat a pass here as a production gate.

| Experiment | Fixtures | Latest scorecard | Notes |
| --- | --- | --- | --- |
| Semantic embed: reps vs `source_text` | [semantic_embed_bakeoff.yaml](semantic_embed_bakeoff.yaml) | [../results/semantic_embed_scorecard.md](../results/semantic_embed_scorecard.md) | 2026-09-16: all arms 8/8 Hit@K on install PDF; **no production change** |
| Embedder A/B: BGE vs Jasper-600M | S4 `fixtures.yaml` | [../results/embedder_ab_scorecard.md](../results/embedder_ab_scorecard.md) | In-memory Jasper index; production `EMBEDDING_MODEL` unchanged |

Re-run:

```powershell
python -m repair_assistant.corpus.cli bench-semantic-embed --write
python -m repair_assistant.corpus.cli bench-embedder-ab --write
```

Jasper chunk vectors cache under `evals/retrieval/drafts/jasper_ab_cache/` (gitignored).
