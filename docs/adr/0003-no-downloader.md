# ADR-0003: The repository ships no downloader

- **Status:** Accepted
- **Date:** 2026-08-25
- **Phase:** 1
- **Supersedes:** an earlier draft of this project that specified a polite,
  `robots.txt`-aware fetcher with an allowlist and `Crawl-delay` support.

## Context

Phase 1 needs about 20 documents on each user's machine, reproducibly. The
natural design is a fetcher: read the manifest, download what is missing, verify
hashes. That was the plan until the sources were examined properly.

### What the investigation found

**`producthelp.whirlpool.com/robots.txt` is permissive.** It allows the article
paths, advertises `Crawl-delay: 5`, publishes a 4,647-URL sitemap with `lastmod`
timestamps, and disallows only `/@*`. Read alone, it invites a polite crawler.

**Whirlpool's Terms of Use are not.** They define the covered "Services" as
"all U.S. and Canadian websites and apps owned or operated by Whirlpool or its
subsidiaries" and then prohibit users from:

> Use any robot, spider, search/retrieval application or other manual or
> automatic device to systematically retrieve, index, "scrape," "data mine" or
> otherwise gather data or content from the Services.

Source: <https://developer.whirlpool.com/terms>, verified 2026-08-25.

**`whirlpool.com` blocks scripted clients outright.** Every scripted request
returned HTTP 403, including requests for `robots.txt` itself. Working around
that would additionally engage the prohibition on circumventing access controls.

### The conflict

`robots.txt` says yes; the Terms of Use say no. They are different instruments:
`robots.txt` is a machine-readable crawler convention with no legal force, while
the Terms are the agreement accepted by using the site. The Terms are broader
and, where they conflict, they govern. A permissive `robots.txt` is not a
licence.

It is worth being clear that the *documents* are public. Anyone may open these
URLs in a browser and download them, and Whirlpool's own support pages direct
owners to do so. The constraint is on **automated** retrieval, not on access.

## Options considered

**Ship the fetcher anyway, for `producthelp` only.** Defensible on a narrow
reading of `robots.txt`, and indefensible once the Terms have been read. Having
read them, doing it anyway would be a deliberate choice to breach them.

**Ship the fetcher, disabled by default.** Moves the breach to the user while
still distributing the tool that performs it. Worse, not better: it looks like
compliance without being compliance.

**Ship a browser-automation acquirer.** Circumvention of a bot-mitigation
control, dressed up. Clearly outside the line.

**Ship no downloader; verify only.** Users acquire documents through their own
browser — ordinary, permitted use of a public web page — and the tool describes
what is needed and verifies what arrives.

## Decision

**Ship no downloader.** `repair-corpus` has `status`, `verify`, `validate`,
`show`, `applies`, `pin` and `export`. It has no `fetch` and no `download`.

On a missing document, `status` prints the publication number, the access
method, the source URL where one is known, the expected local filename, the
expected hash where one is pinned, and any obligation attaching to that
acquisition route.

## Rationale

This is a well-established pattern, not a workaround.

- **Nixpkgs `requireFile`** declares a file by name, URL and hash, refuses to
  fetch it, and errors with instructions on a cache miss. Its documented purpose
  is this situation verbatim: "a useful last-resort workaround for license
  restrictions that prohibit redistribution, or for downloads that are only
  accessible after authenticating interactively in a browser."
- **MAME software lists** commit checksummed catalogues describing tens of
  thousands of files the project deliberately never distributes, and provide
  `-verifysoftware` to check a local collection.
- **NLTK** ships code but not corpora, leaving licence compliance with each user.

The project's stated principles put open-source and legal compliance above
convenience. Twenty documents is a one-time manual acquisition of maybe twenty
minutes. That is a small price for a posture that does not require a caveat.

There is also an engineering argument. A fetcher would need maintenance every
time a CDN path or WAF rule changed, and the paths *do* change: the `{YYYYMM}`
segment in Whirlpool's asset URLs is the upload month and differs between
revisions of the same document. A verifier has no such dependency.

## Consequences

**Good.** No terms are breached and no caveat is needed. No fragile scraping
code to maintain. Integrity guarantees are unchanged, since verification is
independent of how a file arrived. The tool is honest about the human step
rather than hiding it.

**Bad.** Onboarding requires manual work, and a fresh clone cannot reach a
working corpus unattended. CI can never test against real documents, so tests
must cover manifest logic and synthetic PDFs only. Some documents require
ServiceMatters, which imposes a confidentiality obligation (ADR-0005).

**Accepted risk.** Users may still acquire documents from third-party mirrors of
uncertain legality. The project does not direct them there, and
`provenance.access_method` records the intended route.

**Revisit if** Whirlpool publishes an API or an explicit licence for
documentation retrieval, or if right-to-repair regulations begin to mandate
machine-readable access. Note that current statutes mandate free *access*, not
redistribution or automated retrieval — see ADR-0005.
