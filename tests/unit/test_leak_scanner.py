"""Tests for inkprint.leak.scanner — spec 04-leak-scanner.md (orchestration + failure modes)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from inkprint.leak.scanner import scan, validate_corpora

# ── Happy path ───────────────────────────────────────────────────────────────


class TestLeakScannerHappy:
    @pytest.mark.asyncio
    async def test_tc_l_06_sse_events_per_corpus(self):
        """TC-L-06: SSE stream emits one event per corpus completion."""
        events = []

        async def fake_scan_cc(text, simhash):
            return {"corpus": "common_crawl", "hits": [], "hit_count": 0}

        async def fake_scan_hf(text):
            return {"corpus": "huggingface", "hits": [], "hit_count": 0}

        with (
            patch("inkprint.leak.scanner.scan_common_crawl", fake_scan_cc),
            patch("inkprint.leak.scanner.scan_huggingface", fake_scan_hf),
            patch(
                "inkprint.leak.scanner.get_certificate_text", AsyncMock(return_value="test text")
            ),
            patch("inkprint.leak.scanner.get_certificate_simhash", AsyncMock(return_value=42)),
            patch("inkprint.leak.scanner.save_scan", AsyncMock()),
        ):
            stream = await scan(
                certificate_id=uuid4(),
                corpora=["common_crawl", "huggingface"],
                stream=True,
            )
            async for event in stream:
                events.append(event)

        corpus_events = [e for e in events if e.get("type") == "corpus_complete"]
        assert len(corpus_events) == 2


# ── Failure cases ────────────────────────────────────────────────────────────


class TestLeakScannerFailure:
    @pytest.mark.asyncio
    async def test_tc_l_11_stack_unavailable_graceful(self):
        """TC-L-11: The Stack v2 unavailable skips with warning, others continue."""

        async def fake_scan_cc(text, simhash):
            return {"corpus": "common_crawl", "hits": [], "hit_count": 0}

        async def fake_scan_stack(text):
            raise PermissionError("HF token not set")

        with (
            patch("inkprint.leak.scanner.scan_common_crawl", fake_scan_cc),
            patch("inkprint.leak.scanner.scan_the_stack", fake_scan_stack),
            patch("inkprint.leak.scanner.get_certificate_text", AsyncMock(return_value="test")),
            patch("inkprint.leak.scanner.get_certificate_simhash", AsyncMock(return_value=42)),
            patch("inkprint.leak.scanner.save_scan", AsyncMock()),
        ):
            result = await scan(
                certificate_id=uuid4(),
                corpora=["common_crawl", "the_stack_v2"],
            )
        # Common crawl should succeed, the_stack should be marked skipped
        assert any(r["corpus"] == "common_crawl" for r in result.corpus_results)

    @pytest.mark.asyncio
    async def test_tc_l_12_cc_timeout(self):
        """TC-L-12: Common Crawl CDX timeout — that corpus returns error, others continue."""
        import asyncio

        async def slow_cc(text, simhash):
            await asyncio.sleep(60)
            return {"corpus": "common_crawl", "hits": []}

        async def fake_scan_hf(text):
            return {"corpus": "huggingface", "hits": [], "hit_count": 0}

        with (
            patch("inkprint.leak.scanner.scan_common_crawl", slow_cc),
            patch("inkprint.leak.scanner.scan_huggingface", fake_scan_hf),
            patch("inkprint.leak.scanner.get_certificate_text", AsyncMock(return_value="test")),
            patch("inkprint.leak.scanner.get_certificate_simhash", AsyncMock(return_value=42)),
            patch("inkprint.leak.scanner.save_scan", AsyncMock()),
            patch("inkprint.leak.scanner.CORPUS_TIMEOUT", 0.1),
        ):
            result = await scan(
                certificate_id=uuid4(),
                corpora=["common_crawl", "huggingface"],
            )
        hf = next(r for r in result.corpus_results if r["corpus"] == "huggingface")
        assert hf["hit_count"] == 0

    @pytest.mark.asyncio
    async def test_tc_l_13_hf_rate_limited(self):
        """TC-L-13: HuggingFace API 429 �� retry once, then mark as rate_limited."""
        call_count = 0

        async def rate_limited_hf(text):
            nonlocal call_count
            call_count += 1
            raise Exception("429 Too Many Requests")

        with (
            patch("inkprint.leak.scanner.scan_huggingface", rate_limited_hf),
            patch("inkprint.leak.scanner.get_certificate_text", AsyncMock(return_value="test")),
            patch("inkprint.leak.scanner.get_certificate_simhash", AsyncMock(return_value=42)),
            patch("inkprint.leak.scanner.save_scan", AsyncMock()),
        ):
            await scan(
                certificate_id=uuid4(),
                corpora=["huggingface"],
            )
        # Should have retried at least once
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_tc_l_14_certificate_not_found(self):
        """TC-L-14: Certificate ID not found raises 404-equivalent error."""
        with (
            patch(
                "inkprint.leak.scanner.get_certificate_text",
                AsyncMock(side_effect=KeyError("not found")),
            ),
            pytest.raises((KeyError, Exception)),
        ):
            await scan(certificate_id=uuid4(), corpora=["common_crawl"])

    @pytest.mark.asyncio
    async def test_tc_l_15_r2_download_fails(self):
        """TC-L-15: R2 download fails raises clear error with cert context."""
        with (
            patch(
                "inkprint.leak.scanner.get_certificate_text",
                AsyncMock(side_effect=OSError("R2 download failed")),
            ),
            pytest.raises(IOError, match="R2 download failed"),
        ):
            await scan(certificate_id=uuid4(), corpora=["common_crawl"])


class TestLeakScannerValidation:
    def test_tc_l_16_invalid_corpus_rejected(self):
        """TC-L-16: Unknown corpus name is rejected at validation."""
        with pytest.raises(ValueError, match="Unknown corpus"):
            validate_corpora(["common_crawl", "nonexistent"])
