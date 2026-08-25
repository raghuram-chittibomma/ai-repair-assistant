# Corpus Study

What is actually inside these documents, and what that implies for the phases
that follow. This is the "deeply understood" half of Phase 1, and the direct
input to the Phase 2 parser selection.

## Status of this study

| Document | Examined | Basis |
| --- | --- | --- |
| W11320651 Rev B — Tech Sheet | **Yes, in detail** | Acquired; full text extraction analysed below |
| W11156989 Rev A — Tech Sheet | **Yes, in detail** | Acquired; compared page-by-page against W11320651 in §7 |
| W11169652 Rev A — Service Manual | Partially | Acquired (94 pages); structure confirmed, contents not yet analysed |
| W11395614, W11533288 Rev A, W11766193 Rev B — Service Pointers | Metadata only | Acquired; page counts and languages confirmed in §7 |
| W11375982 — Service Pointer | **Content confirmed** | Acquired from a mirror; the corrected Step 10 text is held and recorded as evaluation ground truth |
| Knowledge-base articles (6) | Structure only | Acquired as MHTML; content not yet analysed |
| Everything else | Not acquired | See [ACQUISITION.md](ACQUISITION.md) |

The tech sheet is the right document to have studied first: it is the densest,
the most structurally hostile, and the one the retrieval system will lean on
hardest. Findings from it already determine several Phase 2 decisions.

Sections below marked **pending** are placeholders with the specific questions to
answer, not empty headings. Fill them in as documents arrive rather than
inventing content.

Section 7 was written after the documents actually arrived, and it corrects two
things this study previously got wrong from inference alone. That is recorded
rather than quietly edited, because the size of the gap between inferred and
measured is itself a finding: it is the argument for not trusting §3 either.

---

## 1. W11320651 Rev B — Tech Sheet (examined)

**28 pages, English only, embedded text layer, no OCR needed.**
Internal part marking reads `W11320651B`, dated `04/19`.

> Corrected after acquisition. This was recorded as dual-language English/French
> on the reasonable assumption that a North American service document is
> bilingual. It is not: the French pages belong to the *other* tech sheet,
> W11156989 Rev A, which is 60 pages precisely because it carries both. See §7.

### Declared structure

Its own table of contents, which is a reliable map of the document:

| Section | Pages |
| --- | --- |
| Whirlpool Control Panel | 2 |
| Diagnostic Guide | 3 |
| Service Diagnostic Mode | 3 |
| Human-Machine Interface Test | 4 |
| Software Version Display | 4 |
| Quick Diagnostics Test | 5 |
| Fault/Error Codes | 7–9 |
| Troubleshooting Guide | 10–11 |
| Test Procedures | 12 |
| Manually Unlocking the Door | 24 |
| Component Removal | 25 |
| Wiring Diagrams | 26–27 |

Structures present: a model/feature matrix, a fault/error code table, a
step-by-step diagnostic sequence table with estimated durations, numbered test
procedures with measured resistance and voltage values, ESD and live-voltage
safety warning blocks, connector and pin references, and two pages of wiring
diagrams.

### Cross-reference density

The document is a graph, not a linear text. The error-code table almost never
contains a remedy; it contains a **pointer** to one:

> `F5E2  Lock failure.  See TEST #4: Door Lock System, page 15.`
>
> `F3E2  Wash NTC open or shorted.  See TEST #10a: Wash Temperature Sensor, page 19.`
>
> `F1E2  MCU over- or under-voltage error.  Check household voltage. See TEST #3: Motor Circuit, page 15.`

`TEST #1: ACU Power Check, page 12` alone is referenced from at least five
different error codes. The Quick Diagnostics Test table does the same thing,
routing each of twelve steps to a numbered test.

**Implication for Phase 2 and Phase 4:** retrieving the chunk that contains
`F5E2` returns the string "see TEST #4", which is not an answer. Either chunks
must carry their referenced procedures, or retrieval must follow intra-document
references as a second hop. A naive top-k chunk retriever will confidently
return a pointer and call it a diagnosis. This is the single most consequential
structural finding in the corpus.

### Naive text extraction fails on this document

This is the evidence the Phase 2 parser bake-off exists to address. It is not a
prediction; it is an observation from an actual extraction of this file.

**The same error-code table extracts four different ways within two pages.**

*Four rows collapsed into one line, with the header glued to the front and all
column boundaries gone:*

```
Error Code Problem Checks & Tests F0E1 Load in drum during Clean Washer cycle.
Run Clean Washer cycle only with an empty drum. F0E2 Oversuds Excessive suds in
washer. ... F0E4 High temp error, wash cycle. ... F0E5 Off Balance Load. ...
```

*A code separated from its remedy, whose line then continues into the whole of
the following row:*

```
F1E1

Main relay open or shorted. Main relay issue. Replace ACU. See TEST #1: ACU
Power Check, page 12. F1E2 MCU over- or under-voltage error. ...
```

*One row split across three blank-line-separated blocks:*

```
F3E1

Pressure sensor signal missing or out of range.

See TEST #7: Water Level Sensor, page 17.
```

*And a run of rows that extract cleanly, one per line:*

```
F5E2 Lock failure. See TEST #4: Door Lock System, page 15.
F5E3 Unlock failure. See TEST #4: Door Lock System, page 15.
```

Why this matters concretely: in the F6E1 case the extracted text produces a
block reading `No communication from the HMI detected by ACU. See Test #2:
Human-Machine Interface (HMI), page 14.` **that does not contain the string
`F6E1` anywhere.** A user typing the exact error code shown on their machine
cannot retrieve it by keyword, and an embedding of that block has no signal
tying it to the code either. The failure is silent: the system returns
something plausible rather than nothing.

Figure labels degrade differently. Control panel artwork extracts as
letter-spaced fragments — `h o ld`, `C y c le`, and isolated characters `W`,
`H`, `A` — which become meaningless tokens in any index.

**Conclusions carried into Phase 2:**

1. Text-only extraction is disqualified for tech sheets. Layout-aware or
   table-aware extraction is mandatory, and this document is the benchmark.
2. Chunking must not use blank lines or fixed sizes as boundaries. Both split
   error codes from their remedies here, demonstrably.
3. Every chunk derived from a table row must carry its error code as structured
   metadata, not rely on the code being present in the chunk text.
4. Extraction quality needs a test, not an eyeball. A workable one: assert that
   all ~40 error codes are recoverable and each is bound to its remedy text.

### A wrinkle worth recording

The source contains its own typo: `The was function is still operable` for
"wash", in the F3E5 row. Exact-match retrieval and any test asserting verbatim
strings must tolerate manufacturer typos. Do not silently "correct" source text
during ingestion — it would break hash-based verification and citation fidelity.

---

## 2. W11169652 Rev A — Service Manual (partially examined)

**Pending acquisition.** Known: it is job aid **L-97**, covers 23 base models
across five brands, and contains a section `Test #1: ACU Power Check` whose
Step 10 is wrong (see below).

Questions to answer on acquisition:

- Page count and whether the text layer is embedded throughout or scanned in the
  diagram sections
- Heading hierarchy depth, and whether headings are recoverable structurally or
  only by font size
- How the 23-model applicability is stated — a table, a list, or prose — and its
  verbatim wording
- Whether theory-of-operation prose and step-by-step procedures are visually
  distinguishable to a parser, since they need different chunking
- The exact original wording of Test #1 Step 10, for the precedence evaluation

---

## 3. W11375982 — Technical Service Pointer (structure known)

Two pages, trilingual. Service pointers share a rigid format that is far easier
to parse than the tech sheets, and they carry the highest-value metadata in the
corpus:

- A **models** block, listing base models without engineering digits
- A **serial numbers** block — here, the words "All Serial Numbers"
- An **action required** field, `informational` in this case
- A body naming the document it corrects and the precise location within it

The correction is stated explicitly enough to evaluate against:

> There is incorrect service information in the Service Manual and Tech Sheets
> regarding the ACU diagnostic LED, at *Test #1: ACU Power Check, Step 10*.

Because the bulletin prints the corrected text, the ground truth for the
precedence scenario is knowable **without** obtaining the revised manual — which
is fortunate, since that revision could not be located.

**Implication:** service pointers should be parsed with a format-specific
extractor rather than the general PDF pipeline. Their metadata blocks are
regular, and getting `models` and `serial ranges` out of them correctly is worth
more to answer quality than anything else per page in this corpus.

---

## 4. Knowledge-base articles (structure known, not yet snapshotted)

Short HTML, consistent MindTouch template, consumer register. Three properties
matter:

- **They defer.** The master error-code article states: "These may not be all
  Error Codes that will show for your model. See your Owner's Manual for the
  Error Codes for your specific model." The manufacturer is stating a precedence
  rule outright, and the corpus should honour it rather than infer its own.
- **They are near-duplicates across product categories.** The three F5E2
  articles share whole sentences verbatim while applying to different appliances.
- **They have public revision histories.** This is the corpus's only source of
  genuine, dated manufacturer content changes, and therefore the natural fixture
  for Phase 3 incremental ingestion.

---

## 5. Cross-cutting findings

### Authority and relevance point in different directions

The clearest case in the corpus: for the ACU diagnostic LED question, the
*most* relevant-looking document by any similarity measure is the 100-plus-page
service manual, and it is **wrong**. The correct source is a two-page
informational bulletin. Any ranking that does not model authority explicitly
will get this backwards.

The corpus contains at least four distinct precedence rules, three of them
stated by the manufacturer rather than inferred:

1. Bulletin corrects service manual (W11375982 → W11169652, at a named step)
2. Owner's manual overrides generic knowledge articles (stated in the article)
3. Product-supplied wiring diagram overrides the manual's own (stated in the
   manual, which calls its diagram "typical" and "for training only")
4. Newer publication supersedes older (W11355369 replaces W11156985)

### Applicability is expressed on six independent axes

Observed across the real documents: base model, engineering digit, platform,
serial range, effective-date window, and software version. Any one of them can
exclude a document that matches on all the others. This is why the manifest
models them as separate fields rather than as free text.

### Applicability breadth varies by two orders of magnitude

From `WFW5620HW0` alone (parts list W11320547 Rev C) to 23 base models across
five brands and all serial numbers (service manual W11169652). Both are correct.
A retrieval system tuned on either extreme will mishandle the other.

### Part numbers in the corpus are already stale

Parts list W11320547 Rev C is current as of August 2020. At least three of its
part numbers have since superseded: door lock `W10804741` → `W11565030`,
pressure switch `W11125159` → `W11316246`, control panel `W11294803` →
`W11319991`. No first-party supersession source was found.

This is a product risk, not merely a corpus gap: a grounded, correctly-cited,
verifiably-sourced answer can still send someone to buy a part that no longer
exists. Phase 6 must either qualify part numbers or decline to state them as
current. Recorded in `_excluded.yaml` and as an evaluation scenario.

---

## 6. What this study determines for later phases

| Phase | Determined by this study |
| --- | --- |
| 2 — Parsing | Text-only extraction is disqualified. The tech sheet is the benchmark document, and the error-code table is the pass/fail test. |
| 2 — Chunking | Blank-line and fixed-size boundaries are disqualified. Error codes must be structured metadata on the chunk, not merely text within it. |
| 3 — Ingestion | The KB article revision histories are the only genuine manufacturer revision fixtures available. The revised service manual could not be obtained. |
| 4 — Retrieval | Must filter on applicability before ranking, and must follow intra-document cross-references. Similarity alone provably fails on the F5E2 triple and the ACU LED case. |
| 5 — Precedence | Four real precedence rules exist, three stated by the manufacturer. Model them as data. |
| 6 — Answers | Must abstain on part-number currency. Must distinguish owner-safe from technician-only procedures: the tech sheet opens "For Technicians only" and involves live-voltage measurement. |

---

## 7. Measured findings from the acquired documents

Everything above §7 was reasoned from research; this section was measured from
the files themselves after acquisition. Twelve of twenty documents are held.

### The two tech sheets are near-duplicates, and differ in three distinct ways

This is the most valuable structure in the corpus and it was not anticipated.
W11156989 Rev A (60 pages, English 1–29, French 30–55) and W11320651 Rev B
(28 pages, English) share their English half almost entirely: **13 of 28
comparable pages are byte-identical after whitespace normalisation, including an
unbroken run of eight (pages 4–11).**

Where they differ, they differ in three separable ways, which is what makes the
pair useful rather than merely redundant:

| Page | Difference | What it tests |
| --- | --- | --- |
| 1 | **One token.** Identical safety notice, identical wording throughout; the only differing line is the publication number itself — `W11156989A` against `W11320651B` | Exact-identifier retrieval, with no lexical or semantic signal available to help |
| 3 | **Pure reflow.** The "IMPORTANT: Voltage checks must be made with all connectors attached" paragraph appears in both, moved from line 41 to line 88 | That relocation is not mistaken for a content change; that chunk ordering follows layout, not stream order |
| 12+ | **Genuine addition.** Rev B adds a four-step voltage-measurement procedure absent from the other, and rewords a cross-reference from "See Figure 2, below." to "See Figure 2." | Real incremental revision, including a cross-reference whose wording changed while its target did not |

Page 1 is the sharpest retrieval case in the corpus. Two documents, one
distinguishing token, and that token is exactly what a technician would quote.
No embedding can separate them; only exact identifier matching can.

The reflow on page 3 is a warning about method. Had these pages been compared by
extracted-text equality alone, page 3 would have been reported as changed and
the corpus would have carried a fabricated revision difference.

### Procedure bullets are private-use codepoints, not characters

Both tech sheets render list markers with symbol-font glyphs mapped into the
Unicode private use area: **U+F0D8 (218 occurrences in W11156989A, 109 in
W11320651B) and U+F06E (92 and 46).** These are Wingdings positions, not text.

Naive extraction yields unmappable codepoints where step boundaries should be,
which compounds the extraction failure documented in §1: a procedure loses both
its table structure *and* its list structure. Any parser benchmark in Phase 2
must include a private-use-area mapping table, and the count above is the
metric — 465 markers that must survive parsing as list structure.

This is also why the analysis script for this section crashed on first run: a
`cp1252` console cannot encode U+F06E at all. Worth stating plainly, because the
same class of failure will appear silently inside a parsing pipeline.

### Producer toolchains vary within a single document type

| Document | Producer | Pages |
| --- | --- | --- |
| W11169652 Rev A — service manual | Adobe PDF Library 15.0 | 94 |
| W11156989 Rev A — tech sheet | Adobe PDF Library 15.0 | 60 |
| W11320651 Rev B — tech sheet | Adobe PDF Library 15.0 | 28 |
| W11395614 — service pointer | Microsoft® Word 2013 | 3 |
| W11533288 Rev A — service pointer | Skia/PDF m89 | 1 |
| W11766193 Rev B — service pointer | *(none declared)* | 6 |

The three service pointers — same publisher, same document type, same purpose —
come from three different toolchains, one of which (Skia) is Chrome's print
pipeline. Phase 2 cannot assume that document type predicts internal structure.
Benchmark per producer, not per type.

### Language coverage does not follow document type either

Measured by scanning for French and Spanish markers per page:

- W11395614 — 3 pages, one per language (en/fr/es)
- W11766193 Rev B — 6 pages, two per language; the French pages confirm the
  revision independently, reading `Bulletin technique no : W11766193 Rév. B`
- W11533288 Rev A — 1 page, English only
- W11169652 Rev A — 94 pages, English only

Two manifest entries were corrected against this: W11156989's French half had
been attributed to W11320651, and W11766193 had been recorded as English-only
when it is trilingual. Both errors came from assuming that North American
service documents are uniformly bilingual. They are not, and the variation is
per-document.

### A mirror-sourced document needs internal evidence, not a trusted host

Two of the thirteen held documents came from third-party mirrors rather than Whirlpool:
W11375982 from device.report and W11766193 Rev B from iFixit. Both were recorded as
`oem_public_pdf` until this was checked, in one case while the prose notes on the same
entry said "third-party mirror" — the queryable field disagreed with its own commentary.

This is not pedantry. A mirror can serve a file that has been altered, re-rendered, or is a
different revision than the entry claims, and any later reasoning about how much to trust a
citation has to be able to see that. The schema now carries `third_party_mirror` as an
explicit `access_method`, a test asserts the field agrees with the host in `source_url`, and
`publisher_url_unverified` keeps a reconstructed manufacturer path from being mistaken for
a route anyone has actually used.

Where the host cannot be trusted, authenticity has to come from the document. For
W11375982 the internal evidence is strong: its page count and three languages match what
the manifest predicted before the file was held, its creation timestamp of 2019-06-10
matches the recorded publication month, and it names W11169652 as the target of its
correction exactly as the recorded relationship says it should. W11766193's French pages
state `Bulletin technique no : W11766193 Rév. B`, confirming both number and revision from
inside the file.

Worth noting what the content-hash filename does and does not establish. device.report
names files by sha256 and `9a1c7666…` is precisely the hash of the file we hold — but that
only shows the mirror serves what it indexed. It is an integrity check on the transfer, not
a provenance check on the publisher.

### Consequences for the phases

| Phase | Determined by §7 |
| --- | --- |
| 2 — Parsing | Benchmark per producer toolchain, not per document type. A private-use-area mapping table is mandatory, not optional. |
| 2 — Chunking | Compare candidate chunkers on the tech-sheet pair: identical pages must produce identical chunks, and the page-3 reflow must not read as a change. |
| 3 — Ingestion | Deduplication must operate at page or chunk level. Eight identical pages across two documents will otherwise be indexed twice and crowd out other results. |
| 4 — Retrieval | Page 1 of the tech-sheet pair is the exact-identifier benchmark. Language must be a filter, or a French answer will be returned to an English query from W11156989. |
| 5 — Precedence | The two tech sheets are not revisions of each other; they are parallel documents for different model sets. Precedence must not infer supersession from a shared publication lineage. |
| 6 — Answers | Two of thirteen documents are mirror-sourced. Citation confidence should reflect acquisition route, not treat every held document as equally attested. |
