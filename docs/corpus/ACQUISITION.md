# Corpus Acquisition Guide

How to assemble the local corpus for Whirlpool WFW5620HW0.

Read [../CORPUS_LICENSING.md](../CORPUS_LICENSING.md) first. In short: these documents are
copyrighted, this repository does not contain them, and it does not download them for you.
You acquire them through your own browser and the tool verifies what you have.

Run `repair-corpus status` at any time to see what is still missing.

---

## Verification status of the URLs below

Research established these documents exist and identified where they live, but
`whirlpool.com` returns HTTP 403 to every scripted request, so most URLs could not be
confirmed by direct fetch. Each entry is therefore tagged:

- **confirmed** — content was retrieved and read; the URL demonstrably serves the document
- **pattern** — constructed from Whirlpool's verified CDN URL convention, not fetched
- **search** — locate via ServiceMatters or the Whirlpool manuals page by model number

A **pattern** URL may 404. The `{YYYYMM}` path segment is the asset *upload* month, not the
document date, and it changes between revisions; slug prefixes and revision-letter casing
are inconsistent (`-reva`, `-rev-b`, `-revD` all occur). Treat the pattern as a way to
*retrieve* a URL you already know, not a way to *discover* one. When a pattern URL fails,
fall back to searching by model number.

---

## Where these documents come from

### Whirlpool public asset CDN

```
https://www.whirlpool.com/content/dam/global/documents/{YYYYMM}/{slug}.pdf
https://www.whirlpooldigitalassets.com/content/dam/global/documents/{YYYYMM}/{slug}.pdf
```

Both hosts serve the same paths; the second also accepts an
`/_jcr_content/renditions/original` suffix. No authentication. Open the URL in a normal
browser — scripted clients are blocked by the WAF.

**What the successful acquisitions actually showed.** Five URLs in this file were guesses
when it was written; four resolved. The forms that worked, and are therefore worth copying:

| Document type | Host | Suffix | Example slug |
| --- | --- | --- | --- |
| Service manual, tech sheet | `whirlpool.com` | none | `service-manual-w11169652-reva-27in-front-load-washers` |
| Service pointer | `whirlpooldigitalassets.com` | `/_jcr_content/renditions/original` | `service-pointer-w11533288-reva` |

Three variables defeat naive guessing, so vary them deliberately:

- **The date folder is the filing month, not the document's own date.** W11533288 is dated
  2021-03 and filed under `202110`.
- **Slug case is inconsistent.** `service-pointer-W11395614` is filed uppercase;
  `service-pointer-w11533288-reva` is lowercase. Try both.
- **The revision suffix is sometimes present and sometimes not,** and its style varies:
  `-reva` on the service manual, `-rev-b` on the tech sheet.

### ServiceMatters Limited Access — fallback only

<https://www.servicematters.com/> → "Limited Access" → enter the complete model number.
Free, no account.

**This project treats ServiceMatters as a fallback, not a first choice.** Accepting its
terms includes a confidentiality obligation that binds even quoting the document in a
public issue, and it is a separate legal constraint from copyright. Try the public asset
CDN and the manuals page first, and only fall back here for what cannot be found.

If you do obtain a document this way, say so — the manifest entry's `access_method` must
be changed to `servicematters_limited_access` so the obligation travels with the record.
See [../CORPUS_LICENSING.md](../CORPUS_LICENSING.md#servicematters-limited-access--read-this-before-using-it).

### Whirlpool manuals search

<https://www.whirlpool.com/services/manuals.html> → enter `WFW5620HW`. This is the route
for owner-facing literature (owner's manual, installation instructions, energy guide).

### producthelp knowledge base

<https://producthelp.whirlpool.com/> — public HTML articles. Use "Save page as" in your
browser to snapshot one. Do not crawl the site.

---

## Core documents — applicable to WFW5620HW0

| Publication | Rev | Type | Save as | Source |
| --- | --- | --- | --- | --- |
| W11169652 | A | Service manual (L-97) | `W11169652A.pdf` | **confirmed** [CDN 201905](https://www.whirlpool.com/content/dam/global/documents/201905/service-manual-w11169652-reva-27in-front-load-washers.pdf) |
| W11320651 | B | Tech sheet | `W11320651B.pdf` | **confirmed** [CDN 201905](https://www.whirlpool.com/content/dam/global/documents/201905/tech-sheet-w11320651-rev-b.pdf) |
| W11156989 | A | Tech sheet | `W11156989A.pdf` | **confirmed** [CDN 201901](https://www.whirlpool.com/content/dam/global/documents/201901/tech-sheet-w11156989-reva.pdf) — was a pattern guess, and it resolved |
| W11375982 | — | Service pointer | `W11375982.pdf` | **confirmed** — via mirror, not the CDN; see below |
| W11320547 | C | Repair parts list | `W11320547C.pdf` | **search** — parts list for `WFW5620HW0` |
| W11355369 | ? | Owner's manual | `W11355369.pdf` | **search** — manuals page, `WFW5620HW` |
| W11156977 | ? | Installation instructions | `W11156977.pdf` | **search** — manuals page |
| W11355381 | — | Quick start guide | `W11355381.pdf` | **search** — manuals page |
| W11356840 | — | Energy guide | `W11356840.pdf` | **search** — manuals page |
| W11243716 | — | Wiring diagram | `W11243716.pdf` | **search**; also ships inside the appliance |
| W11156985 | A | Use & care (superseded) | `W11156985A.pdf` | **search** — superseded by W11355369 |

A `?` in the revision column means revisions are known to exist in the wild but we do not
know which one you will get. **Read the revision letter off the document and record it**:
revision is part of logical identity, so `W11355369C.pdf` must be distinguishable from
`W11355369A.pdf`, and both the manifest `revision` field and `local_filename` need
updating once known.

### W11375982 — acquired from a mirror

**Held.** Three pages, English/French/Spanish, filed as `W11375982.pdf`. This is the
corpus's central precedence case: a bulletin that overrides a named passage of the 94-page
service manual for the anchor model, so the `precedence-bulletin-over-manual` family is now
backed by a real document.

It came from a mirror rather than Whirlpool's CDN, which is recorded honestly:
`access_method: third_party_mirror`, `source_url` naming the mirror, and the reconstructed
manufacturer path kept separately as `publisher_url_unverified` because it has never been
shown to resolve.

A mirror can serve an altered or differently-revised file, so authenticity rests on
internal evidence rather than on the host — and here it is unusually strong:

- Three pages in English, French and Spanish, exactly as the manifest entry predicted
  before the file existed locally.
- A PDF creation timestamp of 2019-06-10, matching the recorded June 2019 publication month.
- The corrected Step 10 text present and naming W11169652 as its target, consistent with
  the `corrects` relationship already recorded.
- The mirror names files by content hash, and `9a1c7666…` is exactly the sha256 of the file
  we hold. That proves the mirror serves what it indexed — not that Whirlpool published it,
  which is why the three points above carry the weight.

The route below is retained because the publisher's own copy is still worth obtaining.

Earlier guesses at this URL all truncated the slug. Whirlpool's CDN slugs carry the
document *title*, not merely its publication number — the service manual is filed as
`service-manual-w11169652-reva-27in-front-load-washers` — and the two service pointers
already held looked like exceptions only because their own titles are short. A third-party
index exposed this document's path fragment as
`...w11375982 acu diagnostic led correction ... documents 201906`, giving both the full
slug and the date folder:

```
https://www.whirlpool.com/content/dam/global/documents/201906/service-pointer-w11375982-acu-diagnostic-led-correction.pdf
```

If that does not resolve, a mirror is confirmed to serve the document:

```
https://device.report/m/9a1c76663e0065ef9471aa4cd5024041474c3ad18210ffb18c9102c74f2d7c9f.pdf
```

Set `provenance.source_url` to whichever host the file actually came from. A mirror is
legitimate provenance; an inaccurate `source_url` is not. Check the revision on arrival —
a mirror can serve a different revision than the entry describes.

Failing both, ServiceMatters Limited Access under `WFW5620HW0`, with the confidentiality
consequence noted above. If it cannot be obtained at all, move it to `_excluded.yaml` with
the routes attempted, and demote the scenario family that depends on it. The corrected
Step 10 text is now known and recorded as evaluation ground truth, but knowing the answer
is not the same as holding a citable source — and a corpus that cites a document it does
not have is exactly the failure this project exists to prevent.

## Applicability contrast — deliberately NOT applicable to WFW5620HW0

These are in the corpus on purpose. A retrieval system that surfaces them for a
WFW5620HW0 question is wrong, and we need that to be measurable.

| Publication | Rev | Why it is here | Source |
| --- | --- | --- | --- |
| W11395614 | — | 24-inch platform, hard serial ranges `CF81500000`–`CF84510000` | **confirmed** [digitalassets 201910](https://www.whirlpooldigitalassets.com/content/dam/global/documents/201910/service-pointer-W11395614.pdf/_jcr_content/renditions/original) |
| W11533288 | A | Commercial washer; applicability keyed on *software version* SC.02 vs SC.03 | **confirmed** [digitalassets 202110](https://www.whirlpooldigitalassets.com/content/dam/global/documents/202110/service-pointer-w11533288-reva.pdf/_jcr_content/renditions/original) |
| W11766193 | B | Top-load; carries S-code, effective-date window, serial ranges and engineering-digit wildcards all at once | **confirmed** [ifixit mirror](https://www.ifixit.com/Document/x3h1Ydc4A1mQDVZM/service-pointer-w11766193-revb.pdf) |

## Knowledge articles — producthelp.whirlpool.com

Paths are relative to `https://producthelp.whirlpool.com/`.

**Save with "Webpage, HTML Only"** — not "Webpage, Complete", which writes a sibling
assets folder we neither want nor track. Save directly into `corpus/documents/`.

These six are marked `content_volatile: true` in the manifest. Browser-saved MindTouch
HTML is not byte-reproducible: it carries session tokens, render timestamps and analytics
tags, and two saves of an unchanged page differ. `repair-corpus verify` therefore reports
`drift` rather than `mismatch` for them, and drift is not a failure. Normalised
snapshotting, where a content change can actually be distinguished from noise, is a
Phase 3 deliverable.

| Save as | Path | Note |
| --- | --- | --- |
| `kb-error-codes-front-load.html` | `Laundry/Washers/Product_Info/Washer_Product_Assistance/Error_Codes_in_Front_Load_Washers` | master code table |
| `kb-f5e2-front-load.html` | `Laundry/Washers/Front_Load_Washers/Error_Codes/"F"_Error_Codes/F5_E2_-_Error_Code` | **applicable** |
| `kb-f5e2-top-load.html` | `Laundry/Washers/Top_Load_Washer/Error_Codes_or_Flashing_Lights/"F"_Codes/F5E2_-_Error_Code` | wrong category — distractor |
| `kb-f5e2-laundry-tower.html` | `Laundry/Stacked_Laundry_Center/Laundry_Tower/Error_Codes/Washer/F5E2_Error_Code` | wrong category — distractor |
| `kb-f7e1-front-load.html` | `Laundry/Washers/Product_Info/Washer_Product_Assistance/What_is_an_F7_E1_Error_Code_on_a_Front_Load_Washer` | |
| `kb-f20-fh-front-load.html` | `Laundry/Washers/Product_Info/Washer_Product_Assistance/What_is_an_F20_or_FH_Error_Code_on_a_Front_Load_Washer` | |
| `kb-f21-f02-front-load.html` | `Laundry/Washers/Product_Info/Washer_Product_Assistance/What_is_an_F21_or_F02_Error_Code_on_a_Front_Load_Washer` | |
| `kb-drain-pump-filter.html` | `Laundry/Washers/Front_Load_Washers/Wash_Performance_or_Clothing_Results/Cleaning_and_Maintenance/Cleaning_the_Drain_Pump_Filter` | branches on storage drawer, not model |

The three `F5E2` articles are near-identical in wording and differ only in which product
they apply to. That is the point.

---

## Known to exist, not obtainable

Recorded in [`corpus/manifest/_excluded.yaml`](../../corpus/manifest/_excluded.yaml) so the
gaps stay visible rather than silently absent.

- **W11169652 Rev B** — TSP W11375982 states the service manual "ha[s] been revised", so a
  post-Rev-A edition exists. No public artefact was found. This is the single most valuable
  missing document: it would give Phase 3 a genuine manufacturer revision pair.
- **W11156989 Rev B** — same reasoning, same absence.
- **W11320651 Rev A** — implied by the existence of Rev B.
- **W11320547 Rev A / Rev B** — implied by the existence of Rev C.

If you can obtain any of these through ServiceMatters, please note it in an issue —
without attaching the file.

---

## Open question to resolve while acquiring

**Which tech sheet is authoritative for WFW5620HW0?**

Both are candidates and the evidence is genuinely split:

- **W11156989 Rev A** is attributed to WFW5620HW0 specifically by the one source that ties
  a tech sheet to that exact model.
- **W11320651 Rev B** (04/19) is a 28-page multi-model sheet. Its internal model/feature
  matrix demonstrably lists `WFW5620H` alongside `IFW5900H`, `CFW4084HW`, `WFW560CH`,
  `WFW6620H`, `WFW8620HW`, and `WFW8620CH` — this was verified in the extracted text.
  Being listed in a feature matrix is not the same as being the designated tech sheet,
  and the extraction was too disordered to read the authoritative applicable-models block.

Given W11156989 is dated 01/2019 and W11320651 is dated 04/2019, the likely relationship is
supersession by a consolidated multi-model sheet — but that is inference, not evidence.

**To resolve:** open both rendered PDFs and read the applicable-models block, and search
ServiceMatters Limited Access for `WFW5620HW0` to see which sheet Whirlpool itself returns.
Then set the `supersedes` / `superseded_by` relationship in the manifest and delete this
section.
