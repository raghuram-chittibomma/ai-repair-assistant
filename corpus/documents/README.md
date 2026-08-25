# corpus/documents/

Acquired manufacturer documents go here. **Nothing in this directory is ever
committed** except this README.

These documents are copyrighted by their manufacturers. This project describes
them in `corpus/manifest/` and verifies them here, but never redistributes them.
See [../../docs/CORPUS_LICENSING.md](../../docs/CORPUS_LICENSING.md).

## What to put here

Run `repair-corpus status` to see what is missing, where each document comes
from, and the exact filename to save it as. Full instructions are in
[../../docs/corpus/ACQUISITION.md](../../docs/corpus/ACQUISITION.md).

Filenames must match the manifest's `provenance.local_filename` — for example
`W11169652A.pdf` for the service manual. `repair-corpus verify` reports any file
here that the manifest does not describe, so a typo shows up rather than being
silently ignored.

## After acquiring

```bash
repair-corpus verify          # check against the manifest
repair-corpus pin --write     # record hashes for newly acquired documents
```

`pin` uses trust-on-first-use: it records whatever you acquired. Review the
resulting manifest diff before committing it.
