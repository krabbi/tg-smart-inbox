"""Shared text-processing helpers."""

import re

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def extract_url(text: str) -> str | None:
    """Return the first HTTP/HTTPS URL found in text, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None
