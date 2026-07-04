"""Real text-similarity primitives for leak detection.

The leak scanner reports a "hit" only when a candidate document from a corpus
is a genuine near-duplicate of the submitted text. Near-duplication is measured
with the same 64-bit SimHash used for the fingerprint pipeline: we compute the
Hamming distance between the query's SimHash and each candidate's SimHash and
convert it into a bounded similarity ``score`` in ``[0, 1]``.

This module is pure (no I/O) so it is unit-testable with fixture text and is
shared by every corpus client, replacing the previous hardcoded ``score=0.5``.
"""

from __future__ import annotations

from inkprint.fingerprint.simhash import compute_simhash

# Bits of the 64-bit SimHash that may differ before two texts stop counting as
# a near-duplicate leak. 12/64 ≈ 81% bit-agreement — the same band the
# fingerprint comparator uses for "derivative".
LEAK_HAMMING_THRESHOLD = 12

# SimHash width in bits.
_SIMHASH_BITS = 64


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two 64-bit SimHash values."""
    return bin((a ^ b) & ((1 << _SIMHASH_BITS) - 1)).count("1")


def similarity_score(hamming: int) -> float:
    """Map a Hamming distance to a bounded similarity score in ``[0, 1]``."""
    return round(max(0.0, 1.0 - hamming / _SIMHASH_BITS), 4)


def compare_text(query_simhash: int, candidate_text: str) -> tuple[int, float]:
    """Compare ``candidate_text`` against ``query_simhash``.

    Returns ``(hamming, score)`` where ``hamming`` is the SimHash distance and
    ``score`` is the derived similarity. Empty candidates are maximally distant.
    """
    if not candidate_text.strip():
        return _SIMHASH_BITS, 0.0
    candidate_simhash = compute_simhash(candidate_text)
    hamming = hamming_distance(query_simhash, candidate_simhash)
    return hamming, similarity_score(hamming)


def is_leak(hamming: int, *, threshold: int = LEAK_HAMMING_THRESHOLD) -> bool:
    """Whether a candidate at ``hamming`` distance counts as a genuine leak."""
    return hamming <= threshold
