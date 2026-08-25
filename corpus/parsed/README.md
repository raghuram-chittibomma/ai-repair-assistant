# Parsed chunks

Output of `repair-corpus parse` lands here as:

```text
corpus/parsed/<doc_id>/chunks.jsonl
corpus/parsed/<doc_id>/meta.json
```

These files are derived from copyrighted manufacturer documents and are
**not committed**. Re-run parse locally after cloning.

Load into Postgres with `repair-corpus ingest` (see ADR-0008 /
docs/INFRASTRUCTURE.md).
