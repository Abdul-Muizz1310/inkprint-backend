"""Deterministic text canonicalization for hashing and signing.

This is the ONLY path for producing bytes-for-signing or bytes-for-verification.
"""

from __future__ import annotations

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")


def canonicalize(text: str) -> bytes:
    """Convert text to deterministic canonical bytes.

    Steps:
    1. NFC Unicode normalization
    2. Collapse all contiguous whitespace to a single ASCII space
    3. Strip leading/trailing whitespace
    4. UTF-8 encode
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")
    nfc = unicodedata.normalize("NFC", text)
    collapsed = WHITESPACE_RE.sub(" ", nfc).strip()
    return collapsed.encode("utf-8")
