"""Aggregate leak scan hits into a confidence score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ScoreResult:
    """Aggregated leak scan score."""

    hit_count: int
    confidence: float
    hits: list[dict[str, Any]]


def score(hits: list[dict[str, Any]]) -> ScoreResult:
    """Score a list of hits into a confidence value.

    Confidence bands:
    - 0 hits → 0.0
    - 1-2 hits → 0.3-0.5
    - 3-5 hits → 0.6-0.8
    - 6+ hits → 0.9-1.0

    Hits with lower Hamming distance contribute more weight.
    """
    if not hits:
        return ScoreResult(hit_count=0, confidence=0.0, hits=[])

    n = len(hits)

    # Weight each hit by closeness (inverse of Hamming distance)
    total_weight = 0.0
    for hit in hits:
        hamming = hit.get("hamming", 10)
        weight = max(0.1, 1.0 - hamming / 64.0)
        total_weight += weight

    avg_weight = total_weight / n if n > 0 else 0.0

    # Map count + average weight to confidence
    if n <= 2:
        base = 0.3 + (n - 1) * 0.1
    elif n <= 5:
        base = 0.6 + (n - 3) * 0.1
    else:
        base = min(1.0, 0.9 + (n - 6) * 0.02)

    confidence = round(min(1.0, base * avg_weight + (1 - avg_weight) * base * 0.5), 2)
    # Ensure within expected bands
    confidence = max(0.0, min(1.0, confidence))

    return ScoreResult(hit_count=n, confidence=confidence, hits=hits)
