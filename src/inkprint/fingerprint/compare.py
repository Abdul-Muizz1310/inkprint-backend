"""Fingerprint comparison: Hamming distance + cosine similarity → verdict."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CompareResult:
    """Result of comparing two fingerprints."""

    hamming: int
    cosine: float
    verdict: str
    overlap_pct: int


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two 64-bit integers."""
    return bin(a ^ b).count("1")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _verdict(hamming: int, cosine: float) -> str:
    """Map hamming distance + cosine similarity to a verdict string."""
    if hamming == 0 and cosine >= 0.99:
        return "identical"
    if hamming <= 3 or cosine >= 0.95:
        return "near-duplicate"
    if hamming <= 12 or cosine >= 0.85:
        return "derivative"
    if cosine >= 0.70:
        return "inspired"
    return "unrelated"


def _overlap_pct(hamming: int, cosine: float) -> int:
    """Estimate overlap percentage from fingerprint distances."""
    # Combine both signals: hamming contributes bit-level similarity,
    # cosine contributes semantic similarity. Weight cosine more heavily.
    bit_sim = max(0.0, 1.0 - hamming / 64.0)
    combined = 0.3 * bit_sim + 0.7 * max(0.0, cosine)
    return round(combined * 100)


def compare(
    *,
    parent_simhash: int,
    parent_embedding: list[float],
    child_simhash: int,
    child_embedding: list[float],
) -> CompareResult:
    """Compare two fingerprints and return a structured result."""
    hamming = _hamming_distance(parent_simhash, child_simhash)
    cosine = _cosine_similarity(parent_embedding, child_embedding)
    return CompareResult(
        hamming=hamming,
        cosine=cosine,
        verdict=_verdict(hamming, cosine),
        overlap_pct=_overlap_pct(hamming, cosine),
    )
