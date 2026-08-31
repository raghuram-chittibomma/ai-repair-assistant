# Reference corpus build (Whirlpool WFW5620H)

> **Reference manufacturer build.** This project used Whirlpool front-load washers
> (WFW5620H family, anchor **WFW5620HW0**) to design and prove the pipeline.
> The application code is the **framework**; swap the manifest and your own
> acquired documents for another brand or product family.
>
> For product capabilities and day-to-day use of the app, see the
> [README](../README.md). For deployment layout, see [DEPLOYMENT.md](DEPLOYMENT.md).

This page is the **operational** guide: acquire → verify → parse → ingest → try
search/ask against the reference corpus. It does not redistribute manufacturer PDFs.

---

## Prerequisites

```bash
pip install -e ".[dev]"
git config core.hooksPath .githooks   # refuses to commit document artefacts
```

Copy `.env.example` → `.env.local` with `DATABASE_URL` (LAN Postgres) and later
`OPENAI_API_KEY` for ask/diagnose. Details: [DEPLOYMENT.md](DEPLOYMENT.md),
[INFRASTRUCTURE.md](INFRASTRUCTURE.md).

**Windows:** if `repair-corpus` is not on PATH, use:

```powershell
python -m repair_assistant.corpus.cli <command> ...
```

Examples below use the short form; substitute the module form as needed.

---

## 1. See what the manifest expects

```bash
repair-corpus status
```

On a fresh clone every document will be reported as missing, with instructions:

```
missing   service_manual            W11169652 Rev A   27in Front-Load Washers (L-97)
          how to obtain: oem_public_pdf
          https://www.whirlpool.com/content/dam/global/documents/201905/...
          save as: corpus/documents/W11169652A.pdf
```

Per-document acquisition notes: [corpus/ACQUISITION.md](corpus/ACQUISITION.md).
Licensing and why there is no downloader: [CORPUS_LICENSING.md](CORPUS_LICENSING.md).
What is in these documents: [corpus/CORPUS_STUDY.md](corpus/CORPUS_STUDY.md).

---

## 2. Acquire and file documents

Download PDFs yourself (browser). Then let the tool identify and rename them:

```bash
repair-corpus intake ~/Downloads/whirlpool   # dry run
repair-corpus intake ~/Downloads/whirlpool --apply

repair-corpus verify                  # hash and check against the manifest
repair-corpus pin --write             # record hashes for newly acquired files
repair-corpus show W11375982          # full metadata for one document
repair-corpus applies --model WFW5620HW0
```

`repair-corpus` has no `fetch` or `download` subcommand. That is intentional.

---

## 3. Parse and ingest

```bash
repair-corpus bench-parse             # optional: re-score extractors
repair-corpus parse tech-sheet-w11320651
repair-corpus parse --all             # chunks under corpus/parsed/ (gitignored)
repair-corpus bench-layout            # screenshot layout pack vs ingested chunks

repair-corpus db-migrate
repair-corpus ingest --all            # + local BGE embeddings (free)
```

---

## 4. Smoke the reference model

```bash
repair-corpus search "F5E1 door lock" --model WFW5620HW0
repair-corpus ask "What does F5E2 mean?" --model WFW5620HW0
repair-corpus diagnose --model WFW5620HW0

python -m repair_assistant.api.main   # then open http://localhost:8080/ui
```

---

## Why applicability matters (reference examples)

A repair instruction can be correct and still wrong for your machine. The
manifest models model applicability, serial ranges, revisions, and precedence
as first-class data ([ADR-0004](adr/0004-applicability-and-precedence.md)).

From this corpus:

- **TSP W11375982** corrects service manual W11169652 at “Test #1: ACU Power
  Check, Step 10” — the bulletin overrides the thicker-looking manual.
- **TSP W11395614** sounds relevant (door locks, will not run) but applies only
  to certain 24-inch models/serials — retrieving it for a WFW5620HW0 is a failure.

---

## Extending beyond Whirlpool

1. Add or replace entries under `corpus/manifest/`.
2. Acquire documents yourself; never commit PDF bytes.
3. `parse` → `ingest` → `search` / `ask` / UI.
4. Keep applicability and precedence in the manifest so retrieval stays honest.

North star: [CHARTER.md](CHARTER.md).
