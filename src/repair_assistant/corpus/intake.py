"""Identify freshly downloaded documents and file them into the corpus.

Browsers name downloads however the server told them to, so a folder of fresh
downloads has names like ``service-manual-w11169652-reva-27in-front-load-
washers.pdf`` and ``F5_E2_-_Error_Code.html``. This module works out which
manifest entry each file is, and renames it to the expected ``local_filename``.

Identification is deliberately shallow. It reads filenames, PDF metadata, and
at most the first page of text purely to find a publication number. That is
*identification*, not content extraction: no text is retained, and the parser
question stays open for Phase 2 to decide on benchmark evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Whirlpool publication numbers are 'W' followed by eight digits, sometimes with
# a revision letter appended. Anchored on a non-alphanumeric boundary so that a
# longer number is never truncated into a false match.
_PUB_RE = re.compile(r"(?<![0-9A-Za-z])(W\d{8})([A-Z])?(?![0-9A-Za-z])", re.IGNORECASE)

# CDN slugs spell the revision out instead: '-reva', '-rev-b', '-revD'.
_SLUG_REV_RE = re.compile(r"-rev-?([a-z])(?![a-z0-9])", re.IGNORECASE)


@dataclass
class Candidate:
    """What we managed to work out about one downloaded file."""

    path: Path
    publication_numbers: set[str] = field(default_factory=set)
    revision: str | None = None
    text_sample: str = ""

    declared_locations: set[str] = field(default_factory=set)

    @property
    def is_web_archive(self) -> bool:
        return self.path.suffix.lower() in {".html", ".htm", ".mhtml", ".mht"}


def _from_filename(name: str) -> tuple[set[str], str | None]:
    numbers = {m.group(1).upper() for m in _PUB_RE.finditer(name)}
    revision = None

    for match in _PUB_RE.finditer(name):
        if match.group(2):
            revision = match.group(2).upper()
            break

    if revision is None and (slug := _SLUG_REV_RE.search(name)):
        revision = slug.group(1).upper()

    return numbers, revision


def _pdf_signals(path: Path) -> tuple[set[str], str | None, str]:
    """Publication numbers and revision from PDF metadata and page one."""
    numbers: set[str] = set()
    revision = None
    sample = ""

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:
        return numbers, revision, sample

    try:
        if reader.metadata and reader.metadata.title:
            sample += f" {reader.metadata.title}"
    except Exception:
        pass

    try:
        # First and last page only. Whirlpool prints the part marking on the
        # front of service pointers and the back of tech sheets.
        pages = reader.pages
        for page in {0, len(pages) - 1}:
            sample += " " + (pages[page].extract_text() or "")
    except Exception:
        pass

    for match in _PUB_RE.finditer(sample):
        numbers.add(match.group(1).upper())
        if match.group(2) and revision is None:
            revision = match.group(2).upper()

    return numbers, revision, sample[:4000]


def inspect_download(path: Path) -> Candidate:
    """Work out what a downloaded file is, without judging what to do about it."""
    numbers, revision = _from_filename(path.name)
    candidate = Candidate(path=path, publication_numbers=numbers, revision=revision)

    if path.suffix.lower() == ".pdf":
        pdf_numbers, pdf_revision, sample = _pdf_signals(path)
        candidate.publication_numbers |= pdf_numbers
        candidate.revision = candidate.revision or pdf_revision
        candidate.text_sample = sample
    elif candidate.is_web_archive:
        candidate.text_sample, candidate.declared_locations = _web_archive_signals(path)

    return candidate


# MHTML archives declare the page they captured in a MIME header. This is the
# most reliable identifier available for a saved article -- more so than a
# canonical <link>, since it cannot be altered by page scripts.
_LOCATION_RE = re.compile(r"^(?:Snapshot-)?Content-Location:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def _web_archive_signals(path: Path) -> tuple[str, set[str]]:
    """Text sample and declared source URLs from a saved page or MHTML archive."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError:
        return "", set()

    # MHTML bodies are quoted-printable, which wraps long lines with a trailing
    # '=' soft break. A URL split across two lines will not match a substring
    # search unless those are rejoined first.
    unwrapped = re.sub(r"=\r?\n", "", raw)

    locations = {m.group(1).rstrip('">;,') for m in _LOCATION_RE.finditer(raw)}
    return unwrapped[:200_000], locations


@dataclass
class Match:
    """A proposed filing decision, with the reason it was reached."""

    candidate: Candidate
    document: object | None
    reason: str
    revision_conflict: str | None = None

    @property
    def target_name(self) -> str | None:
        return self.document.local_filename if self.document else None


def _normalise_url(url: str) -> str:
    from urllib.parse import unquote

    return unquote(url or "").rstrip("/").lower()


def _web_archive_match(candidate: Candidate, documents) -> tuple[object | None, str]:
    """Match a saved article to a manifest entry.

    Three signals in decreasing order of trustworthiness: the URL the archive
    declares it captured, the source path appearing anywhere in the file, and
    finally the title. Title matching is last because the three F5E2 articles
    have titles differing only in a space and a hyphen -- relying on it would
    file all three over each other and destroy the corpus's sharpest
    applicability case.
    """
    declared = {_normalise_url(u) for u in candidate.declared_locations}

    for document in documents:
        url = _normalise_url(document.provenance.get("source_url"))
        if url and url in declared:
            return document, "archive declares it captured this exact URL"

    haystack = _normalise_url(f"{candidate.path.name}\n{candidate.text_sample}")
    for document in documents:
        url = _normalise_url(document.provenance.get("source_url"))
        if not url:
            continue
        # The last two path segments, which is enough to separate the three
        # F5E2 articles while tolerating a differently-escaped prefix.
        tail = "/".join(url.split("/")[-2:])
        if tail and tail in haystack:
            return document, f"file contains its source path {tail!r}"

    for document in documents:
        title = document.title.split("(")[0].strip().lower()
        if len(title) > 12 and title in haystack:
            return document, f"title matches {document.title!r}"

    return None, "no declared URL, source path or title matched any manifest entry"


# Relationship types that point outward, from the document doing something to
# the document it acts upon. Their inverses (corrected_by, superseded_by) are
# recorded on the other end of the same edge, so "is related to" is symmetric
# and useless for telling two candidates apart. Direction is what disambiguates.
_OUTBOUND_RELATIONSHIPS = frozenset({"corrects", "supersedes", "references"})


def _by_citation(hits: list) -> list:
    """Narrow candidates using the relationships the manifest already records.

    A bulletin that corrects a manual necessarily prints the manual's
    publication number, so both numbers appear in the bulletin's text and
    matching on number alone finds both documents. Chronology breaks the tie:
    the correcting document names its target, while the target predates the
    correction and cannot mention it. So of two candidates, the one holding an
    outbound edge to the other is the document in hand.

    Only decides when exactly one candidate accounts for all the others, so two
    documents with no relationship between them stay ambiguous rather than being
    resolved by coin toss.
    """
    numbers = {d.publication_number for d in hits}

    def outbound_targets(document) -> set:
        return {
            rel.get("target")
            for rel in (document.data.get("relationships") or [])
            if rel.get("type") in _OUTBOUND_RELATIONSHIPS
            # A same-publication edge points at another revision of the document
            # itself, which says nothing about which candidate this file is.
            and rel.get("target") != document.publication_number
        }

    citing = [d for d in hits if numbers - {d.publication_number} <= outbound_targets(d)]
    return citing if len(citing) == 1 else []


ACCEPTED_SUFFIXES = frozenset({".pdf", ".html", ".htm", ".mhtml", ".mht"})


def plan(manifest, source_dir: Path) -> list[Match]:
    """Decide where each downloaded file should go. Moves nothing."""
    archive_docs = [d for d in manifest.documents if not d.local_filename.endswith(".pdf")]
    pdf_docs = [d for d in manifest.documents if d.local_filename.endswith(".pdf")]

    matches: list[Match] = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ACCEPTED_SUFFIXES:
            continue

        candidate = inspect_download(path)

        if candidate.is_web_archive:
            document, reason = _web_archive_match(candidate, archive_docs)
            matches.append(Match(candidate, document, reason))
            continue

        hits = [d for d in pdf_docs if d.publication_number in candidate.publication_numbers]

        if not hits:
            matches.append(
                Match(candidate, None, "no Whirlpool publication number found in name or content")
            )
            continue

        if len(hits) > 1:
            # Prefer a document whose revision also agrees, then the one whose
            # number appears in the filename rather than merely in the body,
            # then the one that cites the others.
            by_revision = [d for d in hits if d.revision and d.revision == candidate.revision]
            in_name, _ = _from_filename(path.name)
            by_name = [d for d in hits if d.publication_number in in_name]
            hits = by_revision or by_name or _by_citation(hits) or hits

        if len(hits) > 1:
            names = ", ".join(d.citation for d in hits)
            matches.append(Match(candidate, None, f"ambiguous: matches {names}"))
            continue

        document = hits[0]
        conflict = None
        if candidate.revision and document.revision and candidate.revision != document.revision:
            conflict = (
                f"document is Rev {candidate.revision} but the manifest says "
                f"Rev {document.revision}"
            )
        elif candidate.revision and not document.revision:
            conflict = (
                f"document is Rev {candidate.revision} but the manifest records no "
                "revision; the manifest should be updated before filing"
            )

        matches.append(
            Match(
                candidate,
                document,
                f"publication number {document.publication_number}",
                revision_conflict=conflict,
            )
        )

    return matches
