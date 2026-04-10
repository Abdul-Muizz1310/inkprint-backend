"""Tests for inkprint.leak.score — spec 04-leak-scanner.md (scoring logic)."""

import pytest
from inkprint.leak.score import score


class TestLeakScorer:
    def test_tc_l_03_zero_hits(self):
        """TC-L-03: Score with 0 hits returns confidence 0.0."""
        result = score([])
        assert result.confidence == 0.0
        assert result.hit_count == 0

    def test_tc_l_04_moderate_hits(self):
        """TC-L-04: Score with 4 hits returns confidence in [0.6, 0.8]."""
        hits = [
            {"url": f"https://example.com/{i}", "excerpt": "...", "hamming": 5} for i in range(4)
        ]
        result = score(hits)
        assert 0.6 <= result.confidence <= 0.8, (
            f"Expected confidence in [0.6, 0.8], got {result.confidence}"
        )

    def test_tc_l_05_many_hits(self):
        """TC-L-05: Score with 10 hits returns confidence >= 0.9."""
        hits = [
            {"url": f"https://example.com/{i}", "excerpt": "...", "hamming": 3} for i in range(10)
        ]
        result = score(hits)
        assert result.confidence >= 0.9, f"Expected confidence >= 0.9, got {result.confidence}"

    def test_tc_l_07_empty_corpora(self):
        """TC-L-07: No hits from any corpus returns confidence 0.0."""
        result = score([])
        assert result.confidence == 0.0

    def test_tc_l_08_unknown_corpus_raises(self):
        """TC-L-08: Unknown corpus name raises ValueError."""
        from inkprint.leak.scanner import validate_corpora

        with pytest.raises(ValueError):
            validate_corpora(["common_crawl", "nonexistent_corpus"])

    def test_score_weighted_by_hamming(self):
        """Closer Hamming distance hits should contribute more to confidence."""
        close_hits = [
            {"url": "https://example.com/1", "excerpt": "...", "hamming": 2} for _ in range(3)
        ]
        far_hits = [
            {"url": "https://example.com/1", "excerpt": "...", "hamming": 10} for _ in range(3)
        ]
        close_result = score(close_hits)
        far_result = score(far_hits)
        assert close_result.confidence >= far_result.confidence

    def test_tc_l_10_cache_hit(self):
        """TC-L-10: Cache key generation is deterministic for same inputs."""
        from inkprint.leak.scanner import cache_key

        key1 = cache_key("abc123", "common_crawl", "CC-MAIN-2024-50")
        key2 = cache_key("abc123", "common_crawl", "CC-MAIN-2024-50")
        assert key1 == key2

        key3 = cache_key("abc123", "huggingface", "CC-MAIN-2024-50")
        assert key1 != key3
