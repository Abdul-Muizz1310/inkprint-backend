"""Tests for inkprint.leak.similarity — real SimHash-based leak scoring.

These pin the fix for the CRITICAL finding "corpus clients do not perform real
similarity matching" (every hit was hardcoded to score=0.5). Scoring is now a
pure function of the SimHash Hamming distance between the query and candidate.
"""

from __future__ import annotations

from inkprint.fingerprint.simhash import compute_simhash
from inkprint.leak.similarity import (
    LEAK_HAMMING_THRESHOLD,
    compare_text,
    hamming_distance,
    is_leak,
    similarity_score,
)


def test_identical_text_scores_one_and_is_leak() -> None:
    text = "the secret manuscript that was copied verbatim into the corpus " * 3
    sh = compute_simhash(text)
    hamming, score = compare_text(sh, text)
    assert hamming == 0
    assert score == 1.0
    assert is_leak(hamming)


def test_unrelated_text_is_not_a_leak() -> None:
    query = compute_simhash("the quick brown fox jumps over the lazy dog " * 4)
    hamming, score = compare_text(
        query,
        "quantum chromodynamics describes the strong interaction between quarks " * 4,
    )
    assert hamming > LEAK_HAMMING_THRESHOLD
    assert not is_leak(hamming)
    assert score < 1.0


def test_empty_candidate_is_maximally_distant() -> None:
    sh = compute_simhash("some original content")
    hamming, score = compare_text(sh, "   ")
    assert score == 0.0
    assert not is_leak(hamming)


def test_similarity_score_is_bounded_and_monotonic() -> None:
    assert similarity_score(0) == 1.0
    assert similarity_score(64) == 0.0
    # Closer (smaller Hamming) always scores at least as high as farther.
    assert similarity_score(4) > similarity_score(12) > similarity_score(40)
    assert 0.0 <= similarity_score(30) <= 1.0


def test_hamming_distance_counts_differing_bits_symmetrically() -> None:
    assert hamming_distance(0b1010, 0b0011) == 2
    assert hamming_distance(0b0011, 0b1010) == 2
    assert hamming_distance(0, 0) == 0
    # Only the low 64 bits are considered.
    assert hamming_distance(1 << 64, 0) == 0
