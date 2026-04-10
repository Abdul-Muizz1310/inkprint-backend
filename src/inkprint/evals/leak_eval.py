"""Leak detection evaluation (requires live Common Crawl access)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yaml

from inkprint.leak.common_crawl import scan_common_crawl

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"


@dataclass
class LeakEvalResult:
    """Result of leak detection eval suite."""

    true_positives: int
    false_positives: int
    total_known: int
    total_clean: int


def evaluate_leak_probe() -> LeakEvalResult:
    """Evaluate leak detection on the 40-entry dataset.

    Runs Common Crawl CDX queries for each entry.
    This is slow (rate-limited at 1 req/s).
    """
    path = EVALS_DIR / "leak_probe.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    known = data["known_leaked"]
    clean = data["clean"]

    true_positives = 0
    false_positives = 0

    loop = asyncio.new_event_loop()
    try:
        for entry in known:
            result = loop.run_until_complete(scan_common_crawl(entry["text"], simhash=0))
            if result["hit_count"] >= 1:
                true_positives += 1

        for entry in clean:
            result = loop.run_until_complete(scan_common_crawl(entry["text"], simhash=0))
            if result["hit_count"] >= 1:
                false_positives += 1
    finally:
        loop.close()

    return LeakEvalResult(
        true_positives=true_positives,
        false_positives=false_positives,
        total_known=len(known),
        total_clean=len(clean),
    )
