# Corpus Licensing, Copyright, and Acquisition

This document explains what this repository does and does not contain, why, and what
obligations you take on when you assemble a local corpus.

**This is not legal advice.** It records the project's reasoning and the sources behind it
so that the reasoning can be reviewed and corrected.

---

## The three-way separation

This project deliberately keeps three categories of material apart.

| Category | Example | Committed to git? | Licence |
| --- | --- | --- | --- |
| Application code | `src/repair_assistant/` | Yes | Apache-2.0 |
| Corpus manifest and project metadata | `corpus/manifest/*.yaml` | Yes | Apache-2.0 |
| Manufacturer documents | `W11169652A.pdf` | **Never** | Copyright of the manufacturer |

The manifest contains **factual identifiers only**: publication numbers, revision letters,
titles, model applicability, serial ranges, publication dates, source URLs, and
cryptographic hashes. It contains no substantive excerpts of manufacturer text.

Publication numbers, model numbers, error codes, and serial ranges are facts. Facts are
not copyrightable in the United States (*Feist Publications, Inc. v. Rural Telephone
Service Co.*, 499 U.S. 340 (1991)). The manuals that contain those facts are copyrightable
as written works, which is precisely why they are not committed here.

### How this is enforced

Three independent mechanisms, because a README warning is not a guarantee:

1. `.gitignore` excludes `corpus/documents/`, `corpus/_staging/`, and all `*.pdf`.
2. `.githooks/pre-commit` rejects the commit outright, which `.gitignore` cannot do
   against `git add -f`. Install it with `git config core.hooksPath .githooks`.
3. CI fails the build if any manifest entry declares a redistributable SPDX licence
   identifier, or if a document artefact appears in the tree.

---

## Why the repository ships no downloader

Earlier drafts of this project planned a polite, `robots.txt`-aware fetcher. That plan was
withdrawn after reading Whirlpool's actual Terms of Use.

`producthelp.whirlpool.com/robots.txt` is permissive, allowing all article paths with a
`Crawl-delay: 5`. But Whirlpool's Terms of Use define the covered "Services" as:

> ...our Platform, including but not limited to all U.S. and Canadian websites and apps
> owned or operated by Whirlpool or its subsidiaries...

and then prohibit users from:

> Use any robot, spider, search/retrieval application or other manual or automatic device
> to systematically retrieve, index, "scrape," "data mine" or otherwise gather data or
> content from the Services.

Source: <https://developer.whirlpool.com/terms> (verified 2026-08-25).

A permissive `robots.txt` does not override a contract term. `robots.txt` is a
machine-readable crawler convention; the Terms of Use are the agreement you accept by
using the site, and they are broader. Where the two conflict, this project treats the
contract as governing.

Separately, `whirlpool.com` sits behind a WAF that returns HTTP 403 to non-browser user
agents, including for `robots.txt` itself. Working around that would additionally engage
the prohibition on circumventing access measures.

**Consequence:** this repository ships a *verifier*, not a *downloader*. You acquire
documents yourself, through your own browser, and the tool tells you what is missing and
confirms that what you have is what the manifest describes.

### Prior art for this pattern

This is a well-established approach, not an improvisation.

- **Nixpkgs `requireFile`** declares a file by name, URL, and hash, refuses to fetch it,
  and on a cache miss emits an error explaining how to obtain it. Its documented purpose
  is our situation verbatim: "a useful last-resort workaround for license restrictions
  that prohibit redistribution, or for downloads that are only accessible after
  authenticating interactively in a browser."
- **MAME software lists** commit checksummed XML catalogues describing tens of thousands
  of files that the project deliberately never distributes, and provide `-verifysoftware`
  to check a local collection against the catalogue.
- **NLTK** ships code but not corpora, because several datasets have restrictive or
  unclear licensing. Its maintainers' position — that manual download "leaves
  responsibility for license compliance with each user" — is the position taken here.

---

## Sources, and what each obliges you to

### `whirlpool.com` / `whirlpooldigitalassets.com` public PDFs

Service manuals, tech sheets, and service pointers are served from a public asset CDN with
no authentication. They are copyrighted by Whirlpool Corporation. Downloading one for your
own repair or research is ordinary use of a public web page. Redistributing it is not.

`access_method: oem_public_pdf`

### ServiceMatters Limited Access — read this before using it

<https://www.servicematters.com/> is Whirlpool's technician portal. Its "Limited Access"
guest option is free and requires no account, and Whirlpool's own consumer help page
directs owners there to obtain tech sheets.

**It also imposes a confidentiality obligation**, which is a separate legal constraint from
copyright and is easy to overlook. Accepting the ServiceMatters terms includes agreeing:

> ...to keep the content of all Materials confidential. You further agree that all content
> is the sole property of Whirlpool Corporation and may not be sold, reproduced, or
> otherwise distributed without prior written permission.

If you obtain a document through ServiceMatters, you have very likely agreed to keep it
confidential. Do not commit it, publish it, quote it at length in a public issue, or paste
it into a public chat. The manifest records only its publication number and hash, which is
compatible with that obligation.

`access_method: servicematters_limited_access`

### `producthelp.whirlpool.com` knowledge articles

Public HTML consumer-facing articles. Same Terms of Use as above: read them in a browser,
save what you need locally, do not crawl them.

`access_method: oem_public_html`

### Third-party aggregators — not used by this project

ManualsLib, ServiceManuals.net, Appliantology, Elektrotanya, and similar sites host
manufacturer documents. No evidence was found that any of them holds a licence from
Whirlpool; several operate DMCA safe-harbour takedown programmes, which is the posture of
a host of user-uploaded content rather than an authorised distributor. Several require
paid membership.

This project does not direct users to them and does not treat them as authoritative
sources. Where a document could only be located through such a mirror during research,
the manifest records the fact in `_excluded.yaml` rather than presenting it as an
acquisition route.

---

## What right-to-repair law does and does not give you

A common misconception is worth correcting, because it affects what you may assume.

California (Pub. Res. Code § 42488 et seq.), Minnesota (Minn. Stat. § 325E.72), and
Colorado (HB24-1121) **do** cover major appliances, contrary to the frequent claim that
right-to-repair statutes reach only electronics and farm equipment. Massachusetts, the one
most often cited, is automotive-only. California further requires documentation to be made
available **at no charge** to owners and independent repairers.

But two limits matter here:

1. California § 42488.2(c) states that the section "does not require a manufacturer to
   divulge a trade secret or license any intellectual property, including copyrights or
   patents." **Free access is not a redistribution licence.**
2. These statutes reach only products first sold or used on or after roughly 1 July 2021.
   Most existing appliance documentation, including the WFW5620H family literature from
   2019 and 2020, predates that entirely.

So: you may well have a statutory right to *obtain* these documents for free. You do not
have a right to *republish* them, and this project must not.

---

## SPDX declarations

Every manifest entry carries an SPDX licence expression. Manufacturer documents use a
custom identifier:

```yaml
license: LicenseRef-Whirlpool-Proprietary
```

or `NOASSERTION` where the status is genuinely unknown. Both are valid SPDX. Using a
machine-checkable field lets CI hard-fail if anyone ever adds an entry claiming a
redistributable licence, which is a far stronger guarantee than prose.

---

## If you believe something here is wrong

If you are a rights holder and believe this repository contains material it should not,
please open an issue. The project's intent is to contain no manufacturer content at all,
so any such case is a bug and will be treated as one.
