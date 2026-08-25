"""Decode browser-saved MHTML archives into usable HTML text.

Chrome/Edge save pages as MHTML with quoted-printable bodies and soft line
breaks (a trailing '='). Substring matching and HTML parsing both fail unless
those are rejoined and decoded first.
"""

from __future__ import annotations

import email
import quopri
import re
from email import policy
from pathlib import Path


def load_mhtml(path: Path | str) -> str:
    """Return the best-effort HTML (or plain) body from an MHTML file."""
    path = Path(path)
    raw = path.read_bytes()

    # Prefer a direct HTML-body hunt. email.message walk is fragile on the
    # slightly-nonconformant MIME that browsers emit.
    text = raw.decode("utf-8", errors="replace")
    html = _extract_html_body(text)
    if html:
        return html

    message = email.message_from_bytes(raw, policy=policy.default)
    parts = list(message.walk()) if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() != "text/html":
            continue
        content = _part_text(part)
        if content.strip():
            return content

    return _undo_soft_breaks(text)


def _extract_html_body(text: str) -> str | None:
    """Locate the first HTML document in an MHTML blob and QP-decode it."""
    # Soft breaks can split tags and words; rejoin before searching.
    unwrapped = _undo_soft_breaks(text)
    match = re.search(r"(?is)<html\b.*?</html>", unwrapped)
    if not match:
        return None
    body = match.group(0)
    # Decode any remaining quoted-printable sequences (=XX).
    try:
        return quopri.decodestring(body.encode("utf-8", "replace")).decode(
            "utf-8", "replace"
        )
    except Exception:
        return body


def _part_text(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is not None:
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    content = _undo_soft_breaks(str(part.get_payload() or ""))
    encoding = (part.get("Content-Transfer-Encoding") or "").lower()
    if encoding == "quoted-printable":
        return quopri.decodestring(content.encode("utf-8", "replace")).decode(
            "utf-8", "replace"
        )
    return content


def _undo_soft_breaks(text: str) -> str:
    return re.sub(r"=\r?\n", "", text)


def html_to_visible_text(html: str) -> str:
    """Strip tags enough for fixture checks — not a full browser."""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = _undo_soft_breaks(text)
    return re.sub(r"\s+", " ", text).strip()
