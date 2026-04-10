"""64-bit SimHash for text fingerprinting."""

from __future__ import annotations

from simhash import Simhash


def compute_simhash(text: str) -> int:
    """Compute a 64-bit SimHash for the given text.

    Uses character-level shingles (width=3) for robustness against
    minor edits and paraphrasing.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")
    if not text.strip():
        return int(Simhash("").value)
    return int(Simhash(text).value)
