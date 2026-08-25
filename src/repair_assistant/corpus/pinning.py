"""Surgical edits to manifest YAML.

Pinning has to write into files that are mostly prose. Every manifest entry
carries the reasoning for why the document is in the corpus, why its
applicability is shaped the way it is, and what makes it awkward -- and that
reasoning lives in YAML comments, which no YAML library round-trips faithfully.
A load-mutate-dump cycle silently deletes it.

So pinning does not re-serialise. It locates the three lines it is entitled to
change and rewrites those, leaving every other byte alone. The result is a diff
a reviewer can actually read: three or four lines, not four hundred.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


class PinError(Exception):
    """The manifest entry is not shaped the way pinning expects."""


def _scalar(value: object) -> str:
    """Render a value as YAML would, with quoting only where it is needed.

    Delegated to PyYAML rather than hand-rolled, because deciding when a string
    needs quotes is exactly the kind of detail that looks simple and is not:
    ``null``, ``SC.02``, ``2021-03`` and a producer string containing a colon
    all need different treatment.
    """
    dumped = yaml.safe_dump(
        {"k": value}, default_flow_style=False, allow_unicode=True, width=10_000
    )
    return dumped.split(":", 1)[1].strip()


def render_instance(instance: dict, indent: str = "    ") -> list[str]:
    """One acquired-instance record as YAML sequence-item lines."""
    keys = list(instance)
    first, rest = keys[0], keys[1:]
    lines = [f"{indent}- {first}: {_scalar(instance[first])}"]
    lines += [f"{indent}  {key}: {_scalar(instance[key])}" for key in rest]
    return lines


def _identity_span(lines: list[str]) -> tuple[int, int]:
    """Half-open line range of the top-level ``identity:`` block."""
    start = next((i for i, line in enumerate(lines) if line.rstrip() == "identity:"), None)
    if start is None:
        raise PinError("no top-level 'identity:' block")

    # The block runs until the next top-level key. Blank lines and comments
    # belong to it; a line starting in column zero with a name does not.
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            return start, index
    return start, len(lines)


def _replace_value(lines: list[str], key: str, value: object) -> bool:
    pattern = re.compile(rf"^(\s*){re.escape(key)}:\s*(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            lines[index] = f"{match.group(1)}{key}: {_scalar(value)}"
            return True
    return False


def _append_instance(lines: list[str], instance: dict) -> None:
    pattern = re.compile(r"^(\s*)instances:\s*(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue

        indent, existing = match.group(1), match.group(2).strip()
        item_indent = indent + "  "

        # An empty list is written inline as `instances: []`; a populated one is
        # a block sequence on the following lines, leaving nothing after the
        # colon. The two are indistinguishable from this line alone, so find the
        # end of any existing sequence and let that decide.
        insert_at = index + 1
        for probe in range(index + 1, len(lines)):
            line = lines[probe]
            if not line.strip():
                continue  # blank lines inside the block are not a terminator
            if line.startswith(item_indent):
                insert_at = probe + 1
            else:
                break

        # Append rather than prepend, so the instance history reads oldest-first
        # and a reviewer can see which acquisition came from where.
        lines[index] = f"{indent}instances:" if existing == "[]" else lines[index]
        lines[insert_at:insert_at] = render_instance(instance, item_indent)
        return

    raise PinError("no 'instances:' key inside the identity block")


def apply_pin(
    text: str,
    *,
    instance: dict,
    canonical_sha256: str | None = None,
    canonicalizer: str | None = None,
) -> str:
    """Return ``text`` with pinned identity values written in.

    Only lines inside the ``identity:`` block are considered, so a key name that
    also appears elsewhere in the entry cannot be hit by accident.
    """
    lines = text.split("\n")
    start, end = _identity_span(lines)
    block = lines[start:end]

    _append_instance(block, instance)
    if canonical_sha256:
        if not _replace_value(block, "canonical_sha256", canonical_sha256):
            raise PinError("no 'canonical_sha256:' key inside the identity block")
        _replace_value(block, "canonicalizer", canonicalizer)

    lines[start:end] = block
    return "\n".join(lines)


def pin_file(
    path: Path,
    *,
    instance: dict,
    canonical_sha256: str | None = None,
    canonicalizer: str | None = None,
) -> None:
    """Apply a pin to a manifest file in place, keeping LF line endings."""
    updated = apply_pin(
        path.read_text(encoding="utf-8"),
        instance=instance,
        canonical_sha256=canonical_sha256,
        canonicalizer=canonicalizer,
    )
    # newline="" suppresses translation so the LF endings written here survive
    # on Windows, matching what .gitattributes declares for the manifest.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
