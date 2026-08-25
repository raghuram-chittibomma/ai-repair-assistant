# ADR-0005: Copyright separation, SPDX declaration, and licence choice

- **Status:** Accepted
- **Date:** 2026-08-25
- **Phase:** 1

## Context

This is an open-source project built entirely around documentation it does not
own. Whirlpool service manuals, tech sheets and service pointers are
copyrighted works. The project must be genuinely open while never redistributing
any of them, and the separation has to be enforced rather than merely promised.

A tempting shortcut is to assume right-to-repair legislation solves this. It
does not, and the detail matters.

### What right-to-repair law actually provides

Contrary to the common claim that these statutes cover only electronics and farm
equipment, **major appliances are covered** in California (Pub. Res. Code
§ 42488 et seq.), Minnesota (Minn. Stat. § 325E.72) and Colorado (HB24-1121).
Massachusetts, the most frequently cited, is automotive-only. California further
requires documentation to be provided **at no charge**.

Two limits decide the question:

1. California § 42488.2(c) states the section "does not require a manufacturer
   to divulge a trade secret or license any intellectual property, including
   copyrights or patents." **Free access is not a redistribution licence.**
2. These statutes reach products first sold or used on or after roughly
   1 July 2021. The WFW5620H family literature dates from 2019 and 2020 and
   predates them entirely.

So a user may well have a statutory right to *obtain* these documents for
nothing. Nobody has a right to *republish* them.

### A second obligation that is easy to miss

ServiceMatters Limited Access is free, requires no account, and is where
Whirlpool's own consumer pages send owners for tech sheets. Accepting its terms
also includes agreeing:

> ...to keep the content of all Materials confidential. You further agree that
> all content is the sole property of Whirlpool Corporation and may not be sold,
> reproduced, or otherwise distributed without prior written permission.

That is a **contractual confidentiality obligation**, separate from and stricter
than copyright. It binds even quotation in a public issue tracker. Several
documents in this corpus are most readily obtained this way, so it cannot be
ignored.

## Decision

### Three-way separation

| Category | Committed? | Licence |
| --- | --- | --- |
| Application code | Yes | Apache-2.0 |
| Manifest and project metadata | Yes | Apache-2.0 |
| Manufacturer documents | **Never** | Copyright of the manufacturer |

### Apache-2.0 for the code

Over MIT, for the express patent grant in § 3 and the patent-retaliation clause.
A project in the appliance-diagnostics space touches an area with active
patenting, and the explicit grant is worth the slightly longer licence text.
Apache-2.0 is also GPLv3-compatible, so downstream copyleft use stays possible.

### The manifest records facts only

Publication numbers, revisions, titles, model applicability, serial ranges,
dates, URLs and hashes. No substantive excerpts. Facts are not copyrightable in
the United States (*Feist Publications, Inc. v. Rural Telephone Service Co.*,
499 U.S. 340 (1991)), which is what makes the manifest publishable when the
documents are not.

The corpus study and evaluation seeds quote short fragments — a few error-code
table rows, one sentence of a service pointer — for the purpose of documenting
structure and establishing test ground truth. These are brief, transformative,
and used for analysis rather than substitution.

### SPDX declaration, machine-checked

Every entry carries a `provenance.license` SPDX expression. Manufacturer
documents use `LicenseRef-Whirlpool-Proprietary`, or `NOASSERTION` where the
status is genuinely unknown. Both are valid SPDX.

### Enforcement, in three independent layers

A README warning is not a control.

1. `.gitignore` excludes `corpus/documents/`, `corpus/_staging/` and `*.pdf`.
2. `.githooks/pre-commit` rejects the commit, which `.gitignore` cannot do
   against `git add -f`.
3. CI fails the build if any tracked file is a document artefact, or if any
   manifest entry declares a redistributable SPDX identifier or sets
   `redistributable: true`.

Layer 3 is tested directly: `test_licensing_guard_catches_a_bad_entry` poisons a
manifest entry with `MIT` and asserts that validation rejects it, so the guard
itself cannot silently rot.

### Third-party aggregators are not used

ManualsLib, ServiceManuals.net, Appliantology and similar sites host
manufacturer documents. No evidence was found that any holds a licence from
Whirlpool; several run DMCA safe-harbour takedown programmes, which is the
posture of a host of user-uploaded content rather than an authorised
distributor. The project does not direct users to them.

## Consequences

**Good.** The project is genuinely open source while remaining compliant. The
separation is enforced by machinery, not goodwill. Contributors are told about
the ServiceMatters obligation before they trip over it. A rights holder reading
this repository can see quickly that it contains none of their content.

**Bad.** Contributors must acquire documents manually (ADR-0003). Documents
obtained via ServiceMatters cannot be quoted in public discussion, which makes
some debugging conversations awkward. The corpus cannot be published as a
dataset, so reproducibility depends on each user acquiring the same files and
the manifest hashes agreeing.

**Not legal advice.** This records the project's reasoning and its sources so
that both can be reviewed and corrected. If a rights holder believes this
repository contains material it should not, that is a bug and will be treated as
one.
