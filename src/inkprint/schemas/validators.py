"""Reusable field validators shared by the HTTP DTOs.

Kept separate from the DTO modules so the single-certificate and batch request
schemas cannot drift apart — they enforce the *same* rule from the *same* code.
"""

from __future__ import annotations

from inkprint.provenance.canonicalize import has_canonical_content

BLANK_TEXT_MESSAGE = (
    "text must contain at least one non-whitespace character: "
    "whitespace-only input canonicalizes to zero bytes, which cannot be signed"
)


def reject_blank_canonical(value: str) -> str:
    """Return ``value`` unchanged, or raise when it canonicalizes to ``b""``.

    Rejects ``""`` and anything whitespace-only (spaces, tabs, newlines, NBSP,
    line/paragraph separators, ideographic space — everything ``\\s`` matches
    under Unicode semantics). The value itself is never normalized here: the raw
    submitted text is what gets archived, and ``canonicalize()`` remains the sole
    path to signing bytes.
    """
    if not has_canonical_content(value):
        raise ValueError(BLANK_TEXT_MESSAGE)
    return value
