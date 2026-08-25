# Architecture Decision Records

One record per significant decision: the context, the options genuinely
considered, what was chosen, why, and what it costs. A decision without a
recorded cost has usually not been thought through.

Records are immutable once accepted. To change a decision, write a new ADR that
supersedes the old one and update the older record's status. ADR-0003 already
supersedes an earlier draft of this project's acquisition design.

## Phase 1 — Corpus

| ADR | Decision | Driver |
| --- | --- | --- |
| [0001](0001-corpus-manifest-format.md) | Corpus manifest is git-committed YAML, with Croissant as an export | The bytes cannot be redistributed, and every claim must be reviewable in a diff |
| [0002](0002-three-layer-document-identity.md) | Document identity has three layers | PDF byte hashes are unstable by construction, so one hash per document breaks immediately |
| [0003](0003-no-downloader.md) | The repository ships no downloader | Whirlpool's Terms of Use prohibit automated retrieval, notwithstanding a permissive `robots.txt` |
| [0004](0004-applicability-and-precedence.md) | Applicability and precedence are structured data | A correct instruction for the wrong machine is still wrong, and that must be decidable rather than inferred |
| [0005](0005-copyright-separation-and-licence.md) | Three-way copyright separation, Apache-2.0, SPDX, enforced in CI | Free access under right-to-repair law is not a redistribution licence |
