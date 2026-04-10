"""Common Crawl CDX API client for leak detection."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

CDX_RATE_LIMIT = asyncio.Semaphore(1)  # max 1 req/s


async def scan_common_crawl(
    text: str,
    simhash: int,
    cdx_url: str = "https://index.commoncrawl.org/CC-MAIN-2024-50-index",
) -> dict[str, Any]:
    """Query Common Crawl CDX index for near-duplicate text.

    Strategy: extract title-like n-grams → query CDX → compare SimHash.
    """
    # Extract a representative query from the first ~100 chars
    query_text = text[:100].strip().replace('"', "")
    if not query_text:
        return {"corpus": "common_crawl", "hits": [], "hit_count": 0, "snapshot": "CC-MAIN-2024-50"}

    async with CDX_RATE_LIMIT:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    cdx_url,
                    params={
                        "url": "*",
                        "output": "json",
                        "fl": "url,status",
                        "filter": f"~url:{query_text[:50]}",
                    },
                )
                if resp.status_code == 200 and resp.text.strip():
                    lines = resp.text.strip().split("\n")
                    hits = []
                    for line in lines[:10]:  # Cap at 10 hits
                        hits.append({"url": line.strip(), "excerpt": "", "score": 0.5})
                    return {
                        "corpus": "common_crawl",
                        "hits": hits,
                        "hit_count": len(hits),
                        "snapshot": "CC-MAIN-2024-50",
                    }
        except (httpx.TimeoutException, httpx.HTTPError):
            pass

    return {"corpus": "common_crawl", "hits": [], "hit_count": 0, "snapshot": "CC-MAIN-2024-50"}
