"""Document identity and integrity.

Three layers, deliberately not collapsed into one:

1. **Logical identity** -- ``publication_number`` + ``revision``. The
   manufacturer's own key. A fact, stable across every source, and the thing a
   citation should name.
2. **Edition identity** -- SHA-256 over canonicalised bytes. Recognises the same
   edition obtained from two different places.
3. **Instance identity** -- SHA-256 over the raw bytes a user actually holds.
   What ``verify`` checks.

The reason for the split: PDF byte hashes are unstable by construction. The
trailer ``/ID`` is derived partly from the file path and size at write time, so
merely re-saving a document changes its hash while changing nothing a reader
would notice. Creation and modification dates, XMP packets, incremental update
history and object ordering all vary too. A single-hash schema breaks the first
time two people obtain the same manual from two places.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's raw bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileFacts:
    """Cheap, corroborating signals about a local file."""

    sha256: str
    bytes: int
    page_count: int | None = None
    pdf_producer: str | None = None
    is_pdf: bool = False
    # True when a PDF carries no extractable text layer on its first pages,
    # i.e. it is a scan. Phase 2 needs to know this before choosing a parser.
    looks_scanned: bool | None = None


def _pdf_facts(path: Path) -> tuple[int | None, str | None, bool | None]:
    """Page count, producer, and a scanned-document heuristic.

    Metadata only. Content extraction is deliberately out of scope in Phase 1:
    the parser is chosen in Phase 2 on benchmark evidence, and quietly adopting
    one here would prejudge that decision.
    """
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        return None, None, None

    try:
        reader = PdfReader(str(path))
    except Exception:
        # Malformed OEM scans are common. pikepdf/qpdf can often repair them.
        try:
            import pikepdf

            with pikepdf.open(str(path)) as pdf:
                return len(pdf.pages), None, None
        except Exception:
            return None, None, None

    producer = None
    try:
        if reader.metadata and reader.metadata.producer:
            # pypdf returns PDF string objects that subclass str but are not
            # plain str, and PyYAML refuses to serialise them. Coerce here so
            # the manifest writer never sees a library-specific type.
            producer = str(reader.metadata.producer).strip() or None
    except Exception:
        producer = None

    looks_scanned = None
    try:
        sample = reader.pages[: min(3, len(reader.pages))]
        extracted = "".join((page.extract_text() or "") for page in sample)
        looks_scanned = len(extracted.strip()) < 100
    except Exception:
        looks_scanned = None

    return len(reader.pages), producer, looks_scanned


def inspect(path: Path) -> FileFacts:
    """Gather integrity facts about a local document."""
    is_pdf = path.suffix.lower() == ".pdf"
    page_count = producer = looks_scanned = None
    if is_pdf:
        page_count, producer, looks_scanned = _pdf_facts(path)

    return FileFacts(
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
        page_count=page_count,
        pdf_producer=producer,
        is_pdf=is_pdf,
        looks_scanned=looks_scanned,
    )


def canonicalizer_version() -> str | None:
    """Identifier for the normalisation toolchain, or None if unavailable."""
    try:
        import pikepdf
    except ImportError:
        return None
    return f"pikepdf-{pikepdf.__version__}/qpdf-{pikepdf.__libqpdf_version__}"


def canonical_sha256(path: Path) -> str | None:
    """SHA-256 identifying the *edition*, or None if it cannot be computed.

    Rather than re-serialising the whole container and hashing the result, this
    hashes the decoded page content streams plus the page count. Re-saving a PDF
    rewrites the trailer /ID, the creation and modification dates, the XMP
    packet, and object ordering, and it may change stream compression -- none of
    which a reader would notice. Container-level normalisation turns out not to
    remove all of that reliably, whereas the decoded content streams are stable
    across a resave.

    Two known limits, stated rather than hidden:

    - Resources such as embedded fonts and images are not included, so two
      documents with identical text but different figures would collide. For
      distinguishing editions of the same publication that is acceptable; for
      general deduplication it would not be.
    - Stability holds within a toolchain version, not across all versions of
      qpdf. That is why the manifest records the producing toolchain next to the
      hash, and why the raw instance hash remains the authoritative check.
    """
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pikepdf
    except ImportError:
        return None

    try:
        digest = hashlib.sha256()
        with pikepdf.open(str(path)) as pdf:
            digest.update(f"pages:{len(pdf.pages)}\n".encode())
            for index, page in enumerate(pdf.pages):
                content = _page_content_bytes(page)
                digest.update(f"page:{index}:{len(content)}\n".encode())
                digest.update(content)
    except (pikepdf.PdfError, OSError):
        # A document too damaged to open has no edition identity. The raw
        # instance hash still works, so verification degrades rather than fails.
        return None

    return digest.hexdigest()


def _page_content_bytes(page) -> bytes:
    """Decoded content stream of a page, or b'' if it has none.

    ``/Contents`` is either a single stream or an array of streams that a reader
    concatenates, and ``read_bytes`` decodes the compression filters, so the
    result is stable regardless of how the file was compressed on save.
    """
    import pikepdf

    contents = page.get("/Contents")
    if contents is None:
        return b""
    try:
        if isinstance(contents, pikepdf.Array):
            return b"\n".join(bytes(part.read_bytes()) for part in contents)
        return bytes(contents.read_bytes())
    except (pikepdf.PdfError, AttributeError, TypeError):
        return b""
