# ADR-0002: Document identity has three layers

- **Status:** Accepted
- **Date:** 2026-08-25
- **Phase:** 1

## Context

"Which document is this?" has three different answers, and collapsing them into
one field breaks in practice.

The obvious design is a single SHA-256 per document. It fails immediately,
because **PDF byte hashes are unstable by construction**:

- The trailer `/ID` is seeded partly from the file path and file size at write
  time, so the same content written to a different location hashes differently.
- `CreationDate`, `ModDate` and `Producer` are rewritten on save.
- XMP metadata packets are regenerated.
- Object ordering, compression settings and incremental update history all vary.

None of that changes a single character a reader would see. So the same edition
of the same manual, obtained by two people from two sources — or from the same
source through a proxy that re-serialises it — produces two different hashes.
Under a single-hash schema one of those people has a "corrupted" file.

There is a second, independent problem. Whirlpool's own identifiers separate the
publication number from the revision: the tech sheet is `W11320651` at revision
`B`, printed inside the document as `W11320651B`. Precedence reasoning needs to
compare revisions of the same publication, which requires the two to be separate
fields, not one string.

## Decision

Model identity in **three layers**.

**Layer 1 — logical identity.** `publication_number` + `revision`. The
manufacturer's own key, and the thing a citation should name. A fact, stable
across every source. Null for knowledge-base articles, which have no publication
number and are keyed on `source_url` and `source_identifier` instead.

**Layer 2 — edition identity.** `identity.canonical_sha256`: a hash over the
decoded page content streams plus the page count, ignoring the container
metadata that varies between saves. Recognises the same edition across sources.
The producing toolchain is recorded in `identity.canonicalizer` alongside it.

**Layer 3 — instance identity.** `identity.instances`, a **list** of raw
SHA-256 hashes with byte counts, page counts and acquisition provenance. This is
what `repair-corpus verify` checks. It is a list because multiple legitimate
byte-sequences for one logical document is the normal case, not an anomaly.

## Rationale

Each layer answers a question the others cannot.

- *"Which document should I cite?"* → layer 1.
- *"Is your copy the same edition as mine?"* → layer 2.
- *"Is this specific file intact and the one I recorded?"* → layer 3.

Layer 2 was implemented twice. The first attempt normalised the whole container
with qpdf and hashed the resulting bytes; it was not actually stable across a
resave, which the tests caught. Hashing the decoded content streams instead is
both more stable and a more honest definition of "same edition", since it
ignores the container entirely.

The shape is not novel. PREMIS models fixity as repeatable events rather than a
single value, and Software Heritage separates content identity from the many
places content occurs. This is the same idea at a smaller scale.

## Consequences

**Good.** Two people acquiring the same document from different sources both
verify successfully. Revision comparison is a field comparison, not string
parsing. A file that fails layer 3 but passes layer 2 is diagnosable as "same
edition, different source" rather than reported as corruption.

**Bad.** Three fields to keep coherent instead of one. Layer 2 is stable only
within a qpdf toolchain version, which is why the toolchain is recorded and why
layer 3 remains authoritative. Layer 2 ignores embedded fonts and images, so two
documents with identical text but different figures would collide — acceptable
for distinguishing editions of one publication, not acceptable as general
deduplication, and stated as such in the code.

**Deferred:** trust-on-first-use is how instance hashes get recorded
(`repair-corpus pin`). The first person to acquire a document establishes its
hash, reviewed as a diff. There is no upstream signature to verify against,
because the manufacturer publishes none.
