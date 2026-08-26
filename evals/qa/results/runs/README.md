# JSON run logs from `repair-corpus bench-qa --write` and
# `bench-candidates --write`.

Each file is one bench run: timestamp, per-scenario answers, citations, latency,
pass/fail. Filenames:

- Smoke: `{YYYYMMDDTHHMMSSZ}.json`
- Candidates: `candidates-{YYYYMMDDTHHMMSSZ}.json`

## Retention (E9)

These accumulate; there is **no** CI/cron cleanup. Operators prune by hand:

```powershell
# Preview (default)
python -m repair_assistant.corpus.cli prune-eval-runs --keep 5

# Also drop anything older than 30 days
python -m repair_assistant.corpus.cli prune-eval-runs --keep 5 --older-than-days 30

# Actually delete
python -m repair_assistant.corpus.cli prune-eval-runs --keep 5 --execute
```

`--keep` is applied **per prefix** (smoke vs candidates). Do not delete a file
you still need for `promote-eval --run …`.
