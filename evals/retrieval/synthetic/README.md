# Synthetic retrieval documents (eval-only)

These files are **not** OEM literature and are **not** part of the production
corpus.

| Path | Role |
| --- | --- |
| `evals/retrieval/synthetic/` | This pack |
| `corpus/documents/`, `corpus/manifest/` | Real held literature only |

Rules:

1. Every `doc_id` starts with `synth-`.
2. Every `publication_number` starts with `SYNTH-`.
3. Manifests live here, never under `corpus/manifest/`.
4. `repair-corpus ingest` does **not** read this directory.
5. `bench-retrieve` upserts them into Postgres for the bake-off only.
6. Production `search()` excludes `synth-%` / `SYNTH-%` hits.

Use synthetics when a held-corpus gap blocks an IR fixture that the product
class still needs (e.g. new-pub supersession while W11355369 is unobtainable).
