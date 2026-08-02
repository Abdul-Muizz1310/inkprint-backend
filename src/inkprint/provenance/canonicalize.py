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


def has_canonical_content(text: str) -> bool:
    """Return whether ``text`` survives canonicalization as non-empty bytes.

    Whitespace-only input canonicalizes to ``b""`` by design (invariants 2-3), so
    "the string is non-empty" is *not* the same question as "there are bytes to
    sign". Callers that are about to hash or sign must ask this one instead:
    signing ``b""`` binds nothing and collides for every blank submission.
    """
    return canonicalize(text) != b""
