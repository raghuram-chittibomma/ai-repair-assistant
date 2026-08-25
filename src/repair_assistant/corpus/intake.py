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

    @property
    def is_html(self) -> bool:
        return self.path.suffix.lower() in {".html", ".htm"}


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
    elif candidate.is_html:
        try:
            candidate.text_sample = path.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            candidate.text_sample = ""

    return candidate


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


def _html_match(candidate: Candidate, documents) -> tuple[object | None, str]:
    """Match a saved article by the URL or title embedded in the HTML.

    A browser-saved MindTouch page contains its own canonical URL, which is the
    most reliable signal available and survives the page being re-titled.
    """
    haystack = f"{candidate.path.name}\n{candidate.text_sample}".lower()

    for document in documents:
        url = (document.provenance.get("source_url") or "").lower()
        if not url:
            continue
        # Compare on the path tail, since the saved copy may reference the page
        # by a relative or differently-escaped URL.
        tail = url.rstrip("/").split("/")[-1]
        if tail and tail in haystack:
            return document, f"HTML contains its source path {tail!r}"
        from urllib.parse import unquote

        if (plain := unquote(tail)) and plain.lower() in haystack:
            return document, f"HTML contains its source path {plain!r}"

    for document in documents:
        title = document.title.split("(")[0].strip().lower()
        if len(title) > 12 and title in haystack:
            return document, f"HTML title matches {document.title!r}"

    return None, "no source URL or title in the saved HTML matched any manifest entry"


def plan(manifest, source_dir: Path) -> list[Match]:
    """Decide where each downloaded file should go. Moves nothing."""
    html_docs = [d for d in manifest.documents if d.local_filename.endswith(".html")]
    pdf_docs = [d for d in manifest.documents if d.local_filename.endswith(".pdf")]

    matches: list[Match] = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".html", ".htm"}:
            continue

        candidate = inspect_download(path)

        if candidate.is_html:
            document, reason = _html_match(candidate, html_docs)
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
            # number appears in the filename rather than merely in the body.
            by_revision = [d for d in hits if d.revision and d.revision == candidate.revision]
            in_name, _ = _from_filename(path.name)
            by_name = [d for d in hits if d.publication_number in in_name]
            hits = by_revision or by_name or hits

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
