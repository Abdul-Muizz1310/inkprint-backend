"""Integration tests hitting real Common Crawl CDX — spec 04-leak-scanner.md.

These are slow and hit external APIs. Run only in CI nightly or manually.
"""

import httpx
import pytest

from inkprint.leak.common_crawl import scan_common_crawl

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _cdx_reachable() -> bool:
    """Check whether Common Crawl CDX API is reachable."""
    try:
        resp = httpx.get(
            "https://index.commoncrawl.org/CC-MAIN-2024-50-index",
            params={"url": "example.com", "output": "json", "limit": "1"},
            timeout=10.0,
        )
        return resp.status_code == 200
    except (httpx.HTTPError, httpx.TimeoutException, OSError):
        return False


class TestRealCommonCrawl:
    @pytest.mark.asyncio
    @pytest.mark.skipif(not _cdx_reachable(), reason="Common Crawl CDX API unreachable")
    async def test_tc_l_01_known_wikipedia_lead(self):
        """TC-L-01: Known Wikipedia lead returns >= 1 hit from Common Crawl."""
        # Albert Einstein's Wikipedia opening paragraph — guaranteed in CC.
        text = (
            "Albert Einstein was a German-born theoretical physicist who is "
            "widely held to be one of the greatest and most influential "
            "scientists of all time."
        )
        result = await scan_common_crawl(text, simhash=0)
        assert result["hit_count"] >= 1, (
            f"Expected >= 1 hit for known Wikipedia text, got {result['hit_count']}"
        )

    @pytest.mark.asyncio
    async def test_tc_l_02_original_text_no_hits(self):
        """TC-L-02: Original text not in any corpus returns 0 hits."""
        # This text was written for this test and has never been published.
        text = (
            "The zephyr-colored platypus of Montague XIV "
            "rarely practices underwater origami on Tuesdays "
            "unless the barometric pressure exceeds 42 hectopascals "
            "according to the Duchy of Grand Fenwick's meteorological bureau."
        )
        result = await scan_common_crawl(text, simhash=0)
        assert result["hit_count"] == 0, (
            f"Expected 0 hits for original text, got {result['hit_count']}"
        )
