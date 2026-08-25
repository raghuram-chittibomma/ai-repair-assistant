# ADR-0001: The corpus manifest is git-committed YAML

- **Status:** Accepted
- **Date:** 2026-08-25
- **Phase:** 1

## Context

The corpus must be described somewhere. The description has to record document
identity, applicability, precedence, provenance and integrity, and it has to be
reviewable, diffable, and reproducible on a fresh clone.

The defining constraint is unusual: **the bytes cannot be redistributed.**
Manufacturer documentation is copyrighted (see ADR-0005), so whatever we choose
must describe files it will never store or transfer. That rules out the entire
class of tools built around moving large files around.

A second constraint is timing. This is Phase 1. PostgreSQL does not arrive until
Phase 3. Whatever holds the manifest must work with no database at all.

## Options considered

**DVC** — designed for exactly this shape of problem, but its value is in
`dvc pull` against a shared remote. We can never operate that remote for these
files. What remains is a `.dvc` pointer file, which is a hash plus a path — less
than we need, with a tool's worth of overhead.

**git-annex / DataLad** — mature, and `git annex whereis` models "this file
exists but not here" better than anything else available. But both assume the
content is retrievable from *somewhere* once configured, and both impose real
onboarding cost. DataLad additionally pulls in a substantial dependency tree for
a project that currently has four runtime dependencies.

**Frictionless Data Package** — a good standard for tabular data with a JSON
descriptor. Our documents are PDFs, not tables, and the schema machinery would
go unused. Its `path`/`hash` fields are roughly what we want and roughly all we
would use.

**Croissant (MLCommons)** — schema.org-based, describes datasets whose files
live elsewhere, and is understood by Hugging Face and Kaggle. Genuinely close to
our needs. But its RecordSet model targets ML training data, JSON-LD is
unpleasant to hand-edit, and a JSON-LD diff is hard to review.

**A database table** — premature. There is no database in Phase 1, and a
database is not reviewable in a pull request.

## Decision

**One YAML file per document under `corpus/manifest/`, committed to git,
validated against a JSON Schema.** Croissant JSON-LD is supported as an *export*
via `repair-corpus export`, not as the source format.

## Rationale

The manifest's primary consumer in Phase 1 is a **human reviewer**, not a
program. Every claim in it — that a bulletin corrects a manual at a named step,
that a serial range excludes a model, that a document is not redistributable —
is a factual assertion that someone should be able to check in a diff.

One file per document means a change to one document produces a diff touching
one file, and two people adding documents do not conflict. YAML supports
comments, which matters more here than it usually does: several entries need to
record *why* a field says what it says, and where the fact came from.

Keeping Croissant as an export gets the interoperability without paying the
authoring cost. Nothing is lost, because the export is generated.

## Consequences

**Good.** No new tooling to learn or operate. Works on a fresh clone with no
network and no database. Reviewable in a pull request. Comments carry the
provenance of individual facts. Schema validation runs in CI.

**Bad.** No integrity guarantee on the *content* — the manifest can claim
anything, and only `repair-corpus verify` against a local file catches a false
hash. Manual authoring does not scale to thousands of documents; at that point
this decision should be revisited. YAML has real footguns, one of which bit
during implementation: unquoted `2019-12-14` parses as a date object and bare
`2020` as an integer, which is why `manifest.load` normalises temporal fields
rather than demanding everyone remember to quote them.

**Revisit when:** the corpus exceeds a few hundred documents, or entries start
being generated rather than written by hand.
