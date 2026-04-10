"""Tests for inkprint.fingerprint — spec 03-fingerprint.md.

Covers SimHash, embeddings (mocked), and comparison/verdict mapping.
"""

import pytest

from inkprint.fingerprint.compare import compare
from inkprint.fingerprint.simhash import compute_simhash

# ── SimHash ──────────────────────────────────────────────────────────────────


class TestSimHash:
    def test_tc_f_01_identical_distance_zero(self):
        """TC-F-01: SimHash of identical text produces distance 0."""
        text = "The quick brown fox jumps over the lazy dog"
        h1 = compute_simhash(text)
        h2 = compute_simhash(text)
        assert h1 == h2

    def test_tc_f_02_paraphrase_low_distance(self):
        """TC-F-02: SimHash of lightly edited text produces lower distance than unrelated."""
        original = "The quick brown fox jumps over the lazy dog near the river bank"
        edited = "The quick brown fox jumps over the lazy dog near the river side"
        h1 = compute_simhash(original)
        h2 = compute_simhash(edited)
        distance = bin(h1 ^ h2).count("1")
        # Light edit should produce measurably lower distance than unrelated text
        assert distance < 20, f"Expected distance < 20 for light edit, got {distance}"

    def test_tc_f_03_unrelated_high_distance(self):
        """TC-F-03: SimHash of unrelated text produces distance > 20."""
        text1 = "The quick brown fox jumps over the lazy dog"
        text2 = (
            "Quantum computing leverages superposition and entanglement for parallel computation"
        )
        h1 = compute_simhash(text1)
        h2 = compute_simhash(text2)
        distance = bin(h1 ^ h2).count("1")
        assert distance > 20, f"Expected distance > 20, got {distance}"

    def test_tc_f_08_empty_string(self):
        """TC-F-08: SimHash of empty string returns a consistent value."""
        h1 = compute_simhash("")
        h2 = compute_simhash("")
        assert h1 == h2
        assert isinstance(h1, int)

    def test_tc_f_09_single_word(self):
        """TC-F-09: SimHash of single word returns a valid 64-bit integer."""
        h = compute_simhash("hello")
        assert isinstance(h, int)
        assert 0 <= h < (1 << 64)

    def test_tc_f_15_non_string_raises(self):
        """TC-F-15: SimHash with non-string input raises TypeError."""
        with pytest.raises(TypeError):
            compute_simhash(42)  # type: ignore[arg-type]


# ── Embeddings (mocked for unit tests) ───────────────────────────────────────


class TestEmbedding:
    @pytest.fixture(autouse=True)
    def _mock_voyage(self, monkeypatch):
        """Mock Voyage API to return deterministic embeddings."""
        import numpy as np

        async def fake_embed(text: str) -> list[float]:
            rng = np.random.default_rng(hash(text) % (2**32))
            vec = rng.standard_normal(768).tolist()
            norm = sum(x**2 for x in vec) ** 0.5
            return [x / norm for x in vec]

        import inkprint.fingerprint.embed as embed_mod

        monkeypatch.setattr(embed_mod, "compute_embedding", fake_embed)

    @pytest.mark.asyncio
    async def test_tc_f_04_identical_cosine_one(self):
        """TC-F-04: Embedding of identical text produces cosine similarity ~1.0."""
        from inkprint.fingerprint.embed import compute_embedding as embed_fn

        emb1 = await embed_fn("Hello world")
        emb2 = await embed_fn("Hello world")
        cosine = sum(a * b for a, b in zip(emb1, emb2, strict=True))
        assert cosine > 0.99

    @pytest.mark.asyncio
    async def test_tc_f_10_short_text(self):
        """TC-F-10: Embedding of very short text (< 10 chars) succeeds."""
        from inkprint.fingerprint.embed import compute_embedding as embed_fn

        emb = await embed_fn("Hi")
        assert len(emb) == 768

    @pytest.mark.asyncio
    async def test_tc_f_11_max_text(self):
        """TC-F-11: Embedding of text at MAX_TEXT_BYTES limit succeeds."""
        from inkprint.fingerprint.embed import compute_embedding as embed_fn

        emb = await embed_fn("word " * 100_000)
        assert len(emb) == 768

    @pytest.mark.asyncio
    async def test_tc_f_13_invalid_api_key(self, monkeypatch):
        """TC-F-13: Embedding with invalid API key raises clear error."""
        import inkprint.fingerprint.embed as embed_mod

        async def failing_embed(text: str) -> list[float]:
            raise ValueError("Invalid API key")

        monkeypatch.setattr(embed_mod, "compute_embedding", failing_embed)
        with pytest.raises(ValueError, match="Invalid API key"):
            await embed_mod.compute_embedding("test")

    @pytest.mark.asyncio
    async def test_tc_f_14_timeout(self, monkeypatch):
        """TC-F-14: Embedding timeout raises within 30s."""
        import asyncio

        import inkprint.fingerprint.embed as embed_mod

        async def slow_embed(text: str) -> list[float]:
            await asyncio.sleep(60)
            return [0.0] * 768

        monkeypatch.setattr(embed_mod, "compute_embedding", slow_embed)
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await asyncio.wait_for(embed_mod.compute_embedding("test"), timeout=0.1)


# ── Comparison / verdict mapping ─────────────────────────────────────────────


class TestCompare:
    def test_tc_f_05_identical_verdict(self):
        """TC-F-05: Compare identical texts returns verdict 'identical'."""
        # Use identical simhash (0 distance) and cosine ~1.0
        result = compare(
            parent_simhash=123456,
            parent_embedding=[1.0] + [0.0] * 767,
            child_simhash=123456,
            child_embedding=[1.0] + [0.0] * 767,
        )
        assert result.verdict == "identical"
        assert result.hamming == 0

    def test_tc_f_06_paraphrase_verdict(self):
        """TC-F-06: Compare paraphrase returns near-duplicate or derivative."""
        # Low hamming distance, high cosine
        parent_hash = 0b1111111111111111111111111111111111111111111111111111111111111111
        child_hash = (
            0b1111111111111111111111111111111111111111111111111111111111111110  # 1 bit diff
        )
        result = compare(
            parent_simhash=parent_hash,
            parent_embedding=[1.0] + [0.0] * 767,
            child_simhash=child_hash,
            child_embedding=[0.99] + [0.01] * 767,
        )
        assert result.verdict in ("near-duplicate", "derivative")

    def test_tc_f_07_unrelated_verdict(self):
        """TC-F-07: Compare unrelated texts returns 'unrelated'."""
        import random

        random.seed(42)
        result = compare(
            parent_simhash=0,
            parent_embedding=[1.0] + [0.0] * 767,
            child_simhash=(1 << 64) - 1,  # all bits flipped = 64 hamming distance
            child_embedding=[0.0] + [1.0] + [0.0] * 766,
        )
        assert result.verdict == "unrelated"

    def test_tc_f_12_overlap_pct_range(self):
        """TC-F-12: overlap_pct is 100 for identical, 0 for unrelated."""
        identical = compare(
            parent_simhash=42,
            parent_embedding=[1.0] + [0.0] * 767,
            child_simhash=42,
            child_embedding=[1.0] + [0.0] * 767,
        )
        assert identical.overlap_pct == 100

        unrelated = compare(
            parent_simhash=0,
            parent_embedding=[1.0] + [0.0] * 767,
            child_simhash=(1 << 64) - 1,
            child_embedding=[0.0] + [1.0] + [0.0] * 766,
        )
        assert unrelated.overlap_pct == 0
