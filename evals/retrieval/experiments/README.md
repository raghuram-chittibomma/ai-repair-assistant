# Retrieval experiments (not S4)

Draft bake-offs and investigations that are **not** the decision set in
`evals/retrieval/fixtures.yaml`. Do not treat a pass here as a production gate.

| Experiment | Fixtures | Latest scorecard | Notes |
| --- | --- | --- | --- |
| Semantic embed: reps vs `source_text` | [semantic_embed_bakeoff.yaml](semantic_embed_bakeoff.yaml) | [../results/semantic_embed_scorecard.md](../results/semantic_embed_scorecard.md) | 2026-09-16: all arms 8/8 Hit@K on install PDF; **no production change** |

Re-run:

```powershell
python -m repair_assistant.corpus.cli bench-semantic-embed --write
```
